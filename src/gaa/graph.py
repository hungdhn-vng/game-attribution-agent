import io
import time
import pandas as pd

from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.sources.base import BenchmarkSource
from gaa.onboarding.profiler import Profiler
from gaa.orchestrator.router import classify_intent
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.adapters.roblox_adapter import RobloxAdapter
from gaa.jobs.job_store import JobStore
from gaa.jobs.pipeline import AnalysisPipeline


class GraphAgent:
    def __init__(
        self,
        jobs: JobStore,
        pipeline: AnalysisPipeline,
        profile_store: ProfileStore,
        metrics_store: MetricsStore,
        benchmark: BenchmarkSource,
        profiler: Profiler,
        request_budget_s: float = 40.0,
        # Legacy params kept for backward compat (engine, checkpointer ignored)
        engine=None,
        checkpointer=None,
    ) -> None:
        self._jobs = jobs
        self._pipeline = pipeline
        self._profiles = profile_store
        self._metrics = metrics_store
        self._benchmark = benchmark
        self._profiler = profiler
        self._request_budget_s = request_budget_s

    # ---- onboarding helpers ----
    @staticmethod
    def _load_raw(payload: dict, nrows: int | None = None) -> pd.DataFrame:
        """Read the source table from inline `csv_data` (browser upload) or a server-side
        `csv_path`. Pass `nrows` to read only the first rows — used for column-mapping so
        proposal stays fast regardless of how large the uploaded file is."""
        data = payload.get("csv_data")
        if data is not None:
            return pd.read_csv(io.StringIO(data), nrows=nrows)
        return pd.read_csv(payload["csv_path"], nrows=nrows)

    def _onboard_propose(self, payload: dict) -> dict:
        sample = self._load_raw(payload, nrows=20)
        mapping = self._profiler.propose(sample)
        return {"mode": "setup", "mapping": mapping.model_dump(),
                "message": self._profiler.confirmation_message(mapping)}

    def _onboard_confirm(self, payload: dict) -> dict:
        mapping = ColumnMapping(**payload["mapping"])
        adapter = RobloxAdapter() if payload["adapter"] == "roblox" else CSVAdapter()
        df = adapter.load(self._load_raw(payload), mapping)
        self._metrics.save(payload["name"], df)
        self._profiles.save(GameProfile(name=payload["name"], platform=payload["platform"],
                                        genre=payload["genre"], mapping=mapping))
        self._profiles.set_active(payload["name"])
        return {"mode": "setup", "name": payload["name"], "row_count": int(len(df)),
                "metrics": sorted(df["metric"].unique().tolist())}

    # ---- job helpers ----
    def _advance_and_save(self, job, deadline: float | None = None) -> None:
        self._pipeline.advance(job, deadline)
        self._jobs.save(job)

    def _job_response(self, job) -> dict:
        resp = {
            "status": "success",
            "mode": "analyze",
            "job_id": job.job_id,
            "job_status": job.status,
            "stage": job.stage,
            "activity": job.activity,
            "done": job.status == "done",
        }
        if job.status == "done" and job.result:
            resp.update(job.result)
        if job.status == "error":
            resp["error"] = job.error
        return resp

    # ---- public ----
    def handle(self, payload: dict, session_id: str, user_id: str) -> dict:
        action = payload.get("action")

        if action == "onboard_propose":
            return self._onboard_propose(payload)

        if action == "onboard_confirm":
            return self._onboard_confirm(payload)

        if action == "analyze_status":
            job = self._jobs.get(payload["job_id"])
            if job is None:
                return {"status": "error", "error": "unknown job_id"}
            try:
                deadline = time.monotonic() + self._request_budget_s
                self._advance_and_save(job, deadline)
            except Exception as exc:
                return {"status": "error", "error": str(exc)}
            return self._job_response(job)

        # Free-text message path
        message = payload.get("message", "")
        has_active_profile = self._profiles.get_active() is not None
        intent = classify_intent(message, has_active_profile=has_active_profile)

        if intent == "setup":
            return {"status": "success", "mode": "setup",
                    "message": "Let's connect your data. Send your CSV path to onboard "
                               "(action=onboard_propose); I'll propose a column mapping to confirm."}

        # intent == "analyze"
        try:
            job = self._jobs.create(session_id, message)
            deadline = time.monotonic() + self._request_budget_s
            self._advance_and_save(job, deadline)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
        return self._job_response(job)
