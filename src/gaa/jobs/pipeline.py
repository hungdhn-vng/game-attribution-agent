"""Resumable multi-stage analysis pipeline (Task A8).

Stages: plan → crawl → modules → synth → render

Design note on deadline / resumability
---------------------------------------
The deadline check happens BEFORE each stage.  This means:

    while there are stages left:
        if deadline is exceeded → return (job.stage is the NEXT stage to run)
        run stage
        advance job.stage

Consequence: at least one stage always runs per call even if the deadline is
already in the past when advance() is entered, because the check fires before
the *next* stage, not before the first one.  This makes the resume test
deterministic: with ``deadline=time.monotonic()`` (already expired), exactly
one stage runs per call.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from gaa.jobs.models import Job
from gaa.modules.anomaly import AnomalyDetection
from gaa.modules.base import AnalysisContext
from gaa.modules.competitor_signals import CompetitorSignals
from gaa.modules.market_benchmark import MarketBenchmark
from gaa.modules.segment import SegmentDecomposition
from gaa.orchestrator.planner import parse_query
from gaa.render.markdown import to_markdown
from gaa.render.report import render_report
from gaa.schema.hypothesis import AttributionHypothesis
from gaa.schema.ledger import EvidenceLedger
from gaa.synth.concurrent import sample_concurrently
from gaa.synth.gate import apply_gate
from gaa.synth.validator import validate_citations


class AnalysisPipeline:
    """Run the attribution analysis as a sequence of resumable stages.

    Parameters
    ----------
    profiles:
        A ``ProfileStore``-like object with a ``get_active()`` method.
    metrics_store:
        A ``MetricsStore``-like object with a ``load(name) -> DataFrame`` method.
    benchmark:
        A ``CrawlingBenchmarkSource`` (must expose ``set_platform``,
        ``genre_trend``, and ``qualitative_context``).
    refresher:
        A ``BenchmarkRefresher`` with a ``refresh(platform, genre, start, end,
        deadline)`` method.
    synth:
        A ``Synthesizer`` instance.
    signals:
        A ``SignalsSource``-like object.
    n_samples:
        Number of synthesis samples for self-consistency (default 3).
    """

    STAGES = ["plan", "crawl", "modules", "synth", "render"]

    def __init__(
        self,
        profiles: Any,
        metrics_store: Any,
        benchmark: Any,
        refresher: Any,
        synth: Any,
        signals: Any,
        n_samples: int = 3,
    ) -> None:
        self._profiles = profiles
        self._metrics_store = metrics_store
        self.benchmark = benchmark
        self.refresher = refresher
        self.synth = synth
        self.signals = signals
        self.n_samples = n_samples

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def advance(self, job: Job, deadline: Optional[float] = None) -> Job:
        """Run consecutive stages starting at ``job.stage``.

        Stops when the job is done/errored OR when *deadline*
        (a ``time.monotonic()`` value) is exceeded.  The deadline is checked
        BEFORE each stage after the first, so at least one stage executes per
        call — this makes ``advance(job, deadline=time.monotonic())`` advance
        exactly one stage, enabling deterministic resume tests.

        The caller is responsible for persisting the job after this returns.
        """
        try:
            self._run_stages(job, deadline)
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
        return job

    # ------------------------------------------------------------------
    # Internal stage runner
    # ------------------------------------------------------------------

    def _run_stages(self, job: Job, deadline: Optional[float]) -> None:
        stages = self.STAGES
        # Find the index of the current stage
        try:
            idx = stages.index(job.stage)
        except ValueError:
            # Unknown stage — nothing to do
            return

        first = True
        for stage in stages[idx:]:
            # Deadline check: skip on the very first stage of this call,
            # apply on every subsequent stage.
            if not first and deadline is not None and time.monotonic() > deadline:
                return  # job.stage already set to this stage by previous iteration
            first = False

            handler = getattr(self, f"_stage_{stage}")
            handler(job)

            if job.status in ("done", "error"):
                return

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage_plan(self, job: Job) -> None:
        profile = self._profiles.get_active()
        if profile is None:
            job.status = "error"
            job.error = "no active profile"
            return

        df = self._metrics_store.load(profile.name)
        parsed = parse_query(job.query)

        ctx = AnalysisContext(
            profile=profile,
            metrics=df,
            query=job.query,
            metric=parsed["metric"],
            direction=parsed["direction"],
        )
        ledger = EvidenceLedger()
        AnomalyDetection().run(ctx, ledger)

        job.state.update({
            "metric": ctx.metric,
            "start": ctx.start,
            "end": ctx.end,
            "direction": ctx.direction,
            "changepoint": ctx.extras.get("changepoint"),
            "genre": profile.genre,
            "platform": profile.platform,
            "profile_name": profile.name,
            "ledger": [e.model_dump() for e in ledger.all()],
        })
        job.add_activity("plan", f"Scanned metrics → {ctx.metric} over {ctx.start}..{ctx.end}")
        job.stage = "crawl"

    def _stage_crawl(self, job: Job) -> None:
        state = job.state
        self.benchmark.set_platform(state["platform"])
        info = self.refresher.refresh(
            state["platform"],
            state["genre"],
            state.get("start"),
            state.get("end"),
            deadline=None,  # refresher handles its own deadline internally
        )
        qual_note = " (qualitative)" if info.get("qual") else ""
        job.add_activity(
            "crawl",
            f"Benchmark: {info.get('tier')} · {info.get('points', 0)} pts{qual_note}",
        )
        job.stage = "modules"

    def _stage_modules(self, job: Job) -> None:
        state = job.state
        df = self._metrics_store.load(state["profile_name"])

        # Reconstruct profile using the name persisted in plan, NOT get_active(),
        # so that a changed active profile on resume cannot mix profiles.
        profile = self._profiles.get(state["profile_name"])
        if profile is None:
            job.status = "error"
            job.error = f"profile '{state['profile_name']}' no longer exists"
            return

        ctx = AnalysisContext(
            profile=profile,
            metrics=df,
            query=job.query,
            metric=state.get("metric"),
            start=state.get("start"),
            end=state.get("end"),
            direction=state.get("direction"),
            extras={"changepoint": state.get("changepoint")},
        )

        ledger = EvidenceLedger()
        ledger.load(state["ledger"])

        SegmentDecomposition().run(ctx, ledger)
        MarketBenchmark(self.benchmark).run(ctx, ledger)
        CompetitorSignals(self.signals).run(ctx, ledger)

        state["ledger"] = [e.model_dump() for e in ledger.all()]
        job.add_activity(
            "modules",
            f"Segment/Market/Competitor analyzed; ledger has {len(ledger.all())} entries",
        )
        job.stage = "synth"

    def _stage_synth(self, job: Job) -> None:
        state = job.state
        ledger = EvidenceLedger()
        ledger.load(state["ledger"])

        samples = sample_concurrently(self.synth, ledger, job.query, self.n_samples)
        if not samples:
            samples = [self.synth.synthesize(ledger, job.query)]

        hyp = apply_gate(samples[0], samples)
        hyp = validate_citations(hyp, ledger)

        state["hypothesis"] = hyp.model_dump()
        rationale_note = f"; {hyp.rationale}" if hyp.rationale else ""
        job.add_activity(
            "synth",
            f"Sampled {len(samples)}× → {hyp.confidence.likelihood}·{hyp.confidence.evidence_quality}"
            f"{rationale_note}",
        )
        job.stage = "render"

    def _stage_render(self, job: Job) -> None:
        state = job.state
        hyp = AttributionHypothesis.model_validate(state["hypothesis"])

        df = self._metrics_store.load(state["profile_name"])
        metric = state.get("metric")
        if metric:
            series = df[df["metric"] == metric].groupby("date")["value"].sum().sort_index()
        else:
            series = df.groupby("date")["value"].sum().sort_index()

        start = state.get("start") or ""
        end = state.get("end") or ""
        genre_trend: dict = {}
        if state.get("start"):
            genre_trend = self.benchmark.genre_trend(
                state["genre"], state["start"], state["end"]
            )

        html = render_report(
            hyp,
            metric=metric or "metric",
            start=start,
            end=end,
            series=series,
            genre_trend=genre_trend,
        )
        md = to_markdown(hyp)

        job.result = {
            "hypothesis": hyp.model_dump(),
            "markdown_summary": md,
            "html": html,
        }
        job.status = "done"
        job.add_activity("render", "Report ready.")
        # No next stage — job is done.
