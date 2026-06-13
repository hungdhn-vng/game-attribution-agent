from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Optional

from gaa.cli.wiring import GaaContext, build_context
from gaa.runs.store import RunBusy


def _run_view(ctx: GaaContext, run) -> dict:
    """Compact status dict. Heavy artifacts stay on disk; only paths surface."""
    d = ctx.runs.path_for(run.run_id)
    view = {
        "status": run.status,
        "run_id": run.run_id,
        "stage": run.stage,
        "done": run.status == "done",
        "activity": run.activity,
        "ledger_count": len(run.state.get("ledger", [])),
    }
    if run.status == "done":
        view["report_path"] = str(d / "report.html")
        view["summary_path"] = str(d / "summary.md")
    if run.status == "error":
        view["error"] = run.error
    return view


def _emit(obj: dict, as_text: bool) -> None:
    if as_text:
        for k, v in obj.items():
            if k == "activity":
                for a in v:
                    print(f'  · [{a["stage"]}] {a["text"]}')
            else:
                print(f"{k}: {v}")
    else:
        print(json.dumps(obj))


def _cmd_analyze(ctx: GaaContext, args) -> dict:
    run = ctx.runs.create(session=args.session, query=args.query)
    budget = max(0.0, min(float(args.budget), ctx.step_budget_s))
    try:
        with ctx.runs.locked(run.run_id):
            ctx.pipeline.advance(run, deadline=time.monotonic() + budget)
            ctx.runs.save(run)
    except RunBusy:
        # Extremely unlikely for a just-created run; report current state.
        run = ctx.runs.get(run.run_id) or run
    return _run_view(ctx, run)


def _cmd_step(ctx: GaaContext, args) -> dict:
    run = ctx.runs.get(args.run_id)
    if run is None:
        return {"status": "error", "error": f"unknown run: {args.run_id!r}"}
    if run.status != "running":
        return _run_view(ctx, run)
    try:
        with ctx.runs.locked(run.run_id):
            # Re-read inside the lock in case another process advanced it.
            run = ctx.runs.get(args.run_id) or run
            if run.status == "running":
                ctx.pipeline.advance(run, deadline=time.monotonic() + ctx.step_budget_s)
                ctx.runs.save(run)
    except RunBusy:
        run = ctx.runs.get(args.run_id) or run
    return _run_view(ctx, run)


def _cmd_status(ctx: GaaContext, args) -> dict:
    run = ctx.runs.get(args.run_id)
    if run is None:
        return {"status": "error", "error": f"unknown run: {args.run_id!r}"}
    return _run_view(ctx, run)


def _cmd_jobs(ctx: GaaContext, args) -> dict:
    if args.prune:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.prune)).isoformat()
        removed = ctx.runs.prune(cutoff)
        return {"status": "success", "pruned": removed}
    return {"status": "success", "runs": ctx.runs.list(session=args.session)}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gaa", description="Game Attribution Agent CLI")
    p.add_argument("--text", action="store_true", help="human-readable output instead of JSON")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="start a new analysis")
    a.add_argument("query")
    a.add_argument("--session", default="default")
    a.add_argument("--budget", default="20", help="seconds of work on this call (clamped to GAA_STEP_BUDGET_S)")

    s = sub.add_parser("step", help="advance a running analysis one budget slice")
    s.add_argument("run_id")

    st = sub.add_parser("status", help="read run status without advancing")
    st.add_argument("run_id")

    j = sub.add_parser("jobs", help="list runs")
    j.add_argument("--session", default=None)
    j.add_argument("--prune", type=int, default=0, metavar="DAYS",
                   help="delete runs older than DAYS instead of listing")
    return p


_DISPATCH = {
    "analyze": _cmd_analyze,
    "step": _cmd_step,
    "status": _cmd_status,
    "jobs": _cmd_jobs,
}


def main(argv: Optional[list] = None, *, llm: Any = None, today: Optional[str] = None) -> dict:
    """Entry point. Returns the response dict (also printed to stdout).

    ``llm`` / ``today`` are injectable for tests; production passes neither.
    """
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        ctx = build_context(llm=llm, today=today)
        result = _DISPATCH[args.command](ctx, args)
    except Exception as exc:  # never raise to the shell with a traceback
        result = {"status": "error", "error": str(exc)}
    _emit(result, as_text=args.text)
    return result


def cli_entry() -> None:
    """console_scripts shim: exit non-zero on error status."""
    result = main()
    raise SystemExit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    cli_entry()
