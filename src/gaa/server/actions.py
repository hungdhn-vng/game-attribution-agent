"""Shared action dispatch: maps an action name + JSON args dict to the existing
CLI handler functions (each `(ctx, args) -> dict`). Both /chat and /invocations
call dispatch(). Capability handlers (exec/browse/self_edit) are registered by
gaa.server.capabilities at import time via register().
"""
from __future__ import annotations

import logging
import types

logger = logging.getLogger(__name__)

from gaa.cli.main import _cmd_analyze, _cmd_step, _cmd_status, _cmd_jobs
from gaa.cli.commands.primitives import (
    cmd_segments, cmd_detect, cmd_market, cmd_signals, cmd_synth, cmd_report)
from gaa.cli.commands.onboarding import (
    cmd_onboard_propose, cmd_onboard_confirm, cmd_profile_list, cmd_profile_use)
from gaa.cli.commands.config_cmd import cmd_config_get, cmd_config_set
from gaa.cli.commands.doctor import cmd_doctor
from gaa.cli.commands.tools import (
    cmd_tools_list, cmd_tools_show, cmd_tools_promote, cmd_tools_run,
    cmd_tools_remove, cmd_tools_sync_docs, cmd_tools_export, cmd_tools_import)


class _Args(types.SimpleNamespace):
    """Argparse-Namespace stand-in: any attribute a handler reads but we didn't set is None."""
    def __getattr__(self, name):  # only called when normal lookup fails
        return None


# Per-action defaults for attributes the handler will read with a non-None expectation.
_DEFAULTS = {
    "analyze": {"session": "default", "budget": "600", "query": ""},
    "jobs": {"session": None, "prune": None},
    "onboard_propose": {"adapter": "generic"},
    "onboard_confirm": {"adapter": "generic"},
    "tools_sync_docs": {"out": None},
    "tools_export": {"out": None},
}

# Note: handlers reference `args.run` for drilldowns. The model passes "run"; map it.
_HANDLERS = {
    "analyze": _cmd_analyze,
    "step": _cmd_step,
    "status": _cmd_status,
    "jobs": _cmd_jobs,
    "segments": cmd_segments,
    "detect": cmd_detect,
    "market": cmd_market,
    "signals": cmd_signals,
    "synth": cmd_synth,
    "report": cmd_report,
    "onboard_propose": cmd_onboard_propose,
    "onboard_confirm": cmd_onboard_confirm,
    "profile_list": cmd_profile_list,
    "profile_use": cmd_profile_use,
    "config_get": cmd_config_get,
    "config_set": cmd_config_set,
    "doctor": cmd_doctor,
    "tools_list": cmd_tools_list,
    "tools_show": cmd_tools_show,
    "tools_promote": cmd_tools_promote,
    "tools_run": cmd_tools_run,
    "tools_remove": cmd_tools_remove,
    "tools_sync_docs": cmd_tools_sync_docs,
    "tools_export": cmd_tools_export,
    "tools_import": cmd_tools_import,
}

# Actions requiring an admin context (state-changing or dangerous). exec/browse/self_edit
# are added by capabilities.register().
ADMIN_ACTIONS = {
    "config_set", "onboard_confirm", "profile_use", "tools_promote", "tools_run",
    "tools_remove", "tools_import",
}

# Actions whose success should trigger a vStorage snapshot. self_edit is added by register().
MUTATING_ACTIONS = {
    "onboard_confirm", "config_set", "profile_use", "tools_promote", "tools_remove",
    "tools_import",
}


def register(name: str, handler, *, admin: bool = False, mutating: bool = False) -> None:
    """Register a capability handler (called by gaa.server.capabilities)."""
    _HANDLERS[name] = handler
    if admin:
        ADMIN_ACTIONS.add(name)
    if mutating:
        MUTATING_ACTIONS.add(name)


def dispatch(ctx, action: str, args: dict, *, is_admin: bool) -> dict:
    handler = _HANDLERS.get(action)
    if handler is None:
        return {"status": "error", "error": f"unknown action: {action!r}"}
    if action in ADMIN_ACTIONS and not is_admin:
        return {"status": "error", "error": f"action {action!r} requires admin context"}
    merged = dict(_DEFAULTS.get(action, {}))
    merged.update(args or {})
    # The agent's tool guide uses `run` for status/step/drilldowns, but the status/step
    # handlers read `run_id` while drilldown handlers read `run`. Alias the two so the
    # handler finds the id regardless of which key the model supplied.
    if "run" in merged and "run_id" not in merged:
        merged["run_id"] = merged["run"]
    elif "run_id" in merged and "run" not in merged:
        merged["run"] = merged["run_id"]
    try:
        return handler(ctx, _Args(**merged))
    except Exception as exc:  # never crash the loop on a bad action
        logger.exception("action %r failed", action)
        return {"status": "error", "error": str(exc)}
