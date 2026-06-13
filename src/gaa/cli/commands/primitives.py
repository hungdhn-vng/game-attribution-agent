from __future__ import annotations

from typing import Callable

from gaa.core.modules.anomaly import AnomalyDetection
from gaa.core.modules.competitor_signals import CompetitorSignals
from gaa.core.modules.market_benchmark import MarketBenchmark
from gaa.core.modules.segment import SegmentDecomposition
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.runs.store import RunBusy


def load_run_context(ctx, run):
    """Reconstruct (AnalysisContext, EvidenceLedger) from a run's persisted plan-state.

    Raises ValueError if the run has not completed its plan stage (no profile_name).
    """
    state = run.state
    name = state.get("profile_name")
    if not name:
        raise ValueError("run has no plan-state yet — start it with `gaa analyze` first")
    profile = ctx.profiles.get(name)
    if profile is None:
        raise ValueError(f"profile {name!r} no longer exists")
    df = ctx.metrics.load(name)
    actx = AnalysisContext(
        profile=profile, metrics=df, query=run.query,
        metric=state.get("metric"), start=state.get("start"), end=state.get("end"),
        direction=state.get("direction"), extras={"changepoint": state.get("changepoint")},
    )
    ledger = EvidenceLedger()
    ledger.load(state.get("ledger", []))
    return actx, ledger


def run_module_primitive(ctx, run_id: str, module_label: str,
                         body: Callable[[AnalysisContext, EvidenceLedger], None]) -> dict:
    """Lock the run, reconstruct context+ledger, invoke body (which appends to the
    ledger), persist the enriched ledger, and report only the newly-added entries."""
    run = ctx.runs.get(run_id)
    if run is None:
        return {"status": "error", "error": f"unknown run: {run_id!r}"}
    try:
        with ctx.runs.locked(run_id):
            run = ctx.runs.get(run_id) or run
            actx, ledger = load_run_context(ctx, run)
            before = len(ledger.all())
            body(actx, ledger)
            new_entries = [e.model_dump() for e in ledger.all()[before:]]
            run.state["ledger"] = [e.model_dump() for e in ledger.all()]
            run.add_activity(module_label, f"drilldown added {len(new_entries)} ledger entr"
                             f"{'y' if len(new_entries) == 1 else 'ies'}")
            ctx.runs.save(run)
    except RunBusy:
        return {"status": "error", "error": f"run {run_id!r} is busy (another step in progress)"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "run_id": run_id, "module": module_label,
            "new_entries": new_entries, "ledger_count": before + len(new_entries)}


def cmd_segments(ctx, args) -> dict:
    dims = [args.dimension] if args.dimension else None
    return run_module_primitive(
        ctx, args.run, "segment",
        lambda actx, ledger: SegmentDecomposition(dims=dims).run(actx, ledger))


def cmd_detect(ctx, args) -> dict:
    def body(actx, ledger):
        if args.metric:
            actx.metric = args.metric
        AnomalyDetection().run(actx, ledger)
    return run_module_primitive(ctx, args.run, "anomaly", body)


def cmd_market(ctx, args) -> dict:
    return run_module_primitive(
        ctx, args.run, "market",
        lambda actx, ledger: MarketBenchmark(ctx.benchmark).run(actx, ledger))


def cmd_signals(ctx, args) -> dict:
    return run_module_primitive(
        ctx, args.run, "competitor",
        lambda actx, ledger: CompetitorSignals(ctx.signals).run(actx, ledger))
