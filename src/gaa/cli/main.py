from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Optional

from gaa.cli.commands.config_cmd import cmd_config_get, cmd_config_set
from gaa.cli.commands.doctor import cmd_doctor
from gaa.cli.commands.onboarding import (
    cmd_onboard_propose, cmd_onboard_confirm, cmd_profile_list, cmd_profile_use)
from gaa.cli.commands.primitives import cmd_segments, cmd_detect, cmd_market, cmd_signals, cmd_synth, cmd_report
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

    a.set_defaults(func=_cmd_analyze)
    s.set_defaults(func=_cmd_step)
    st.set_defaults(func=_cmd_status)
    j.set_defaults(func=_cmd_jobs)

    d = sub.add_parser("doctor", help="check environment health")
    d.set_defaults(func=cmd_doctor)

    cfg = sub.add_parser("config", help="get/set runtime configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cg = cfg_sub.add_parser("get", help="show config (all keys, or one)")
    cg.add_argument("key", nargs="?", default=None)
    cg.set_defaults(func=cmd_config_get)
    cs = cfg_sub.add_parser("set", help="set or clear a config key")
    cs.add_argument("key")
    cs.add_argument("value")
    cs.set_defaults(func=cmd_config_set)

    ob = sub.add_parser("onboard", help="connect a game's data")
    ob_sub = ob.add_subparsers(dest="onboard_command", required=True)
    obp = ob_sub.add_parser("propose", help="LLM proposes a column mapping from the first rows")
    obp.add_argument("--csv", required=True)
    obp.add_argument("--adapter", choices=["csv", "roblox"], default="csv")
    obp.set_defaults(func=cmd_onboard_propose)
    obc = ob_sub.add_parser("confirm", help="ingest the file with a confirmed mapping")
    obc.add_argument("--csv", required=True)
    obc.add_argument("--mapping", required=True, help="ColumnMapping as a JSON string")
    obc.add_argument("--name", required=True)
    obc.add_argument("--platform", required=True)
    obc.add_argument("--genre", required=True)
    obc.add_argument("--adapter", choices=["csv", "roblox"], default="csv")
    obc.set_defaults(func=cmd_onboard_confirm)

    pf = sub.add_parser("profile", help="manage game profiles")
    pf_sub = pf.add_subparsers(dest="profile_command", required=True)
    pfl = pf_sub.add_parser("list", help="list profiles + the active one")
    pfl.set_defaults(func=cmd_profile_list)
    pfu = pf_sub.add_parser("use", help="set the active profile")
    pfu.add_argument("name")
    pfu.set_defaults(func=cmd_profile_use)

    seg = sub.add_parser("segments", help="decompose a run's movement by segment (Adtributor)")
    seg.add_argument("--run", required=True)
    seg.add_argument("--dimension", default=None,
                     help="focus one dimension (region/version/cohort/device/source/platform)")
    seg.set_defaults(func=cmd_segments)

    det = sub.add_parser("detect", help="re-run change-point / anomaly detection")
    det.add_argument("--run", required=True)
    det.add_argument("--metric", default=None, help="target a specific metric")
    det.set_defaults(func=cmd_detect)

    mkt = sub.add_parser("market", help="re-run the market counterfactual")
    mkt.add_argument("--run", required=True)
    mkt.set_defaults(func=cmd_market)

    sig = sub.add_parser("signals", help="re-fetch competitor/event signals")
    sig.add_argument("--run", required=True)
    sig.set_defaults(func=cmd_signals)

    syn = sub.add_parser("synth", help="re-synthesize a hypothesis from the run's current ledger")
    syn.add_argument("--run", required=True)
    syn.add_argument("question", nargs="?", default=None,
                     help="optional follow-up question (defaults to the run's original query)")
    syn.set_defaults(func=cmd_synth)

    rep = sub.add_parser("report", help="re-render the dossier from the run's current hypothesis")
    rep.add_argument("--run", required=True)
    rep.set_defaults(func=cmd_report)

    return p


def main(argv: Optional[list] = None, *, llm: Any = None, today: Optional[str] = None) -> dict:
    """Entry point. Returns the response dict (also printed to stdout).

    ``llm`` / ``today`` are injectable for tests; production passes neither.
    """
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        ctx = build_context(llm=llm, today=today)
        result = args.func(ctx, args)
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
