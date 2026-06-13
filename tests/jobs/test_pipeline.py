"""Tests for the resumable AnalysisPipeline (Task A8)."""
from __future__ import annotations

import time
import tempfile
import os

import pandas as pd
import pytest

from gaa.jobs.models import Job
from gaa.jobs.pipeline import AnalysisPipeline
from gaa.core.llm.client import FakeLLM
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.sources.fixtures import FixtureSignalsSource
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.profile_store import ProfileStore
from gaa.core.synth.synthesizer import Synthesizer
from gaa.core.crawl.refresher import BenchmarkRefresher


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_PRESET = {
    "main_story": "DAU dropped — internal issues in the survival genre.",
    "rationale": "Region SEA drove most of the decline.",
    "causes": {
        "internal": [
            {
                "claim": "SEA segment collapsed post-update",
                "evidence_ids": ["L1"],
                "likelihood": "Likely",
            }
        ],
        "market": [
            {
                "claim": "Genre trend was slightly negative",
                "evidence_ids": ["L1"],
                "likelihood": "Possible",
            }
        ],
    },
    "scenarios": [
        {
            "description": "Hotfix stabilises SEA within 2 weeks",
            "likelihood": "Possible",
            "evidence_ids": ["L1"],
            "signals_to_watch": ["D7 retention SEA"],
        }
    ],
    "risks": [
        {
            "description": "User churn accelerates if no fix",
            "likelihood": "Possible",
            "evidence_ids": [],
        }
    ],
    "assumptions_and_gaps": ["No UA spend data available"],
}

_BENCHMARK_DATES = {
    "2026-05-01": 100.0,
    "2026-05-02": 99.0,
    "2026-05-03": 97.0,
}


def _make_metrics_df() -> pd.DataFrame:
    """Small canonical DAU df with two regions so SegmentDecomposition has data."""
    rows = []
    for d, sea, na in [("2026-05-01", 1000.0, 800.0), ("2026-05-03", 400.0, 770.0)]:
        rows.append({"date": d, "metric": "dau", "value": sea, "region": "SEA"})
        rows.append({"date": d, "metric": "dau", "value": na, "region": "NA"})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["platform", "version", "cohort", "device", "source"]:
        df[col] = None
    return df


class _Fixtures:
    """Bundle of all pipeline dependencies built in a temp directory."""

    def __init__(self, tmp_path: str) -> None:
        # ProfileStore
        self.profile_store = ProfileStore(os.path.join(tmp_path, "profiles.db"))
        profile = GameProfile(
            name="SurvivalGame",
            platform="roblox",
            genre="survival",
            mapping=ColumnMapping(
                date_col="date",
                metric_cols={"dau": "dau"},
                dim_cols={},
            ),
        )
        self.profile_store.save(profile)
        self.profile_store.set_active("SurvivalGame")
        self.profile = profile

        # MetricsStore
        self.metrics_store = MetricsStore(os.path.join(tmp_path, "metrics"))
        self.metrics_store.save("SurvivalGame", _make_metrics_df())

        # BenchmarkStore — pre-seeded so refresher short-circuits as "fresh"
        bstore = BenchmarkStore(os.path.join(tmp_path, "bench.db"))
        bstore.put_quant("roblox", "survival", raw=_BENCHMARK_DATES)
        self.bstore = bstore

        # CrawlingBenchmarkSource
        self.benchmark = CrawlingBenchmarkSource(bstore)

        # BenchmarkRefresher — empty providers so it hits is_fresh → "fresh"
        self.refresher = BenchmarkRefresher(bstore, providers_by_platform={}, web_provider=None)

        # Synthesizer with preset hypothesis citing L1
        self.synth = Synthesizer(FakeLLM(_PRESET))

        # Signals source — no external events
        self.signals = FixtureSignalsSource([])

    def make_pipeline(self, n_samples: int = 2) -> AnalysisPipeline:
        return AnalysisPipeline(
            profiles=self.profile_store,
            metrics_store=self.metrics_store,
            benchmark=self.benchmark,
            refresher=self.refresher,
            synth=self.synth,
            signals=self.signals,
            n_samples=n_samples,
        )

    def make_job(self) -> Job:
        return Job(job_id="test-job-001", session="sess1", query="why did dau drop?")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_run_produces_done_job(tmp_path):
    """advance(job, deadline=None) runs all five stages and sets status=done."""
    fx = _Fixtures(str(tmp_path))
    pipeline = fx.make_pipeline()
    job = fx.make_job()

    pipeline.advance(job, deadline=None)

    assert job.status == "done", f"expected done, got {job.status!r} (error: {job.error!r})"
    assert job.result is not None
    assert job.result["hypothesis"]["main_story"], "main_story must be set"
    assert "<html" in job.result["html"].lower(), "html output must contain <html"
    assert job.result["markdown_summary"], "markdown_summary must be non-empty"


def test_full_run_activity_covers_all_stages(tmp_path):
    """All five stages must produce at least one activity entry each."""
    fx = _Fixtures(str(tmp_path))
    pipeline = fx.make_pipeline()
    job = fx.make_job()

    pipeline.advance(job, deadline=None)

    stages_seen = {a["stage"] for a in job.activity}
    for stage in AnalysisPipeline.STAGES:
        assert stage in stages_seen, f"stage {stage!r} missing from activity"


def test_resume_across_polls_reaches_done(tmp_path):
    """Repeatedly calling advance with an already-expired deadline advances
    exactly one stage per call (run-one-then-check-deadline design).

    The test confirms:
    - Multiple calls are needed to finish (not all stages in one call).
    - activity grows monotonically between calls.
    - The final result is identical to the one from a full (deadline=None) run.
    """
    fx = _Fixtures(str(tmp_path))
    pipeline = fx.make_pipeline()

    # Full-run reference
    job_ref = fx.make_job()
    pipeline.advance(job_ref, deadline=None)
    assert job_ref.status == "done"

    # Resume-style run: pass an already-expired deadline each time
    pipeline2 = fx.make_pipeline()
    job = Job(job_id="test-job-002", session="sess2", query="why did dau drop?")

    call_count = 0
    prev_activity_len = 0
    max_calls = len(AnalysisPipeline.STAGES) + 2  # safety ceiling

    while job.status == "running" and call_count < max_calls:
        prev_stage = job.stage
        deadline = time.monotonic()  # already expired by the time advance() checks it
        pipeline2.advance(job, deadline=deadline)
        call_count += 1

        # Activity must grow (each stage adds at least one entry)
        assert len(job.activity) >= prev_activity_len, "activity must not shrink"
        prev_activity_len = len(job.activity)

        # Stage must have advanced (or job is now done/error) — a buggy advance
        # that only updates activity but not stage would fail here.
        if job.status == "running":
            assert job.stage != prev_stage, (
                f"stage did not advance after call {call_count}: "
                f"still at {job.stage!r}"
            )

    assert job.status == "done", (
        f"job did not reach done after {call_count} calls; "
        f"stuck at stage={job.stage!r}, status={job.status!r}, error={job.error!r}"
    )
    # Multiple polls were needed — can't be 1 because there are 5 stages
    assert call_count > 1, "resume test should require multiple advance() calls"

    # Result content must match the full run
    assert (
        job.result["hypothesis"]["main_story"]
        == job_ref.result["hypothesis"]["main_story"]
    )
    assert "<html" in job.result["html"].lower()
    assert job.result["markdown_summary"]


def test_no_active_profile_sets_error(tmp_path):
    """advance() sets status=error with a descriptive message when no profile is active."""
    # ProfileStore with no active profile set
    ps = ProfileStore(os.path.join(str(tmp_path), "p.db"))
    bstore = BenchmarkStore(os.path.join(str(tmp_path), "b.db"))
    ms = MetricsStore(os.path.join(str(tmp_path), "m"))
    benchmark = CrawlingBenchmarkSource(bstore)
    refresher = BenchmarkRefresher(bstore, {}, web_provider=None)
    synth = Synthesizer(FakeLLM(_PRESET))
    signals = FixtureSignalsSource([])

    pipeline = AnalysisPipeline(
        profiles=ps,
        metrics_store=ms,
        benchmark=benchmark,
        refresher=refresher,
        synth=synth,
        signals=signals,
    )
    job = Job(job_id="err-job", session="s", query="why dau drop?")
    pipeline.advance(job, deadline=None)

    assert job.status == "error"
    assert "no active profile" in (job.error or "").lower()


def test_stage_exception_sets_error_does_not_raise(tmp_path):
    """If a stage raises an exception, advance() catches it, sets status='error'
    and populates job.error — it must NOT propagate the exception to the caller."""
    fx = _Fixtures(str(tmp_path))

    # Replace synth with an object whose synthesize() raises to force a synth-stage error.
    class _BoomSynth:
        def synthesize(self, ledger, query):
            raise RuntimeError("synth exploded")

    pipeline = AnalysisPipeline(
        profiles=fx.profile_store,
        metrics_store=fx.metrics_store,
        benchmark=fx.benchmark,
        refresher=fx.refresher,
        synth=_BoomSynth(),
        signals=fx.signals,
        n_samples=1,
    )
    job = fx.make_job()

    # Must not raise
    pipeline.advance(job, deadline=None)

    assert job.status == "error", f"expected error, got {job.status!r}"
    assert job.error, "job.error must be populated"
    assert "synth exploded" in job.error
