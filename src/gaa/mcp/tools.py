"""GAA analysis exposed as MCP tools — framework-free core.

Wraps the existing action seam (gaa.server.actions.dispatch over gaa.core). The
general capabilities (exec/browse/self_edit) are intentionally NOT here — OpenClaw
owns those. Admin-class tools are filtered out of non-admin listings (defense in
depth on top of dispatch's own admin gate).

MCP surface is an intentional focused subset: rarer maintenance/admin actions
(step, tools_remove, tools_import, tools_export, tools_sync_docs) are intentionally
NOT exposed as agent tools — they remain reachable via the CLI/ops."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import jsonschema

from gaa.server import actions
from gaa import persist

_log = logging.getLogger(__name__)

_STR = {"type": "string"}

_SPECS: dict[str, tuple[str, dict]] = {
    "analyze": ("Start a new attribution analysis for a game's metric change; runs to completion and returns a run_id.",
                {"type": "object", "properties": {"query": _STR, "session": _STR}, "required": ["query"]}),
    "segments": ("Decompose a run's change by a dimension.",
                 {"type": "object", "properties": {"run": _STR, "dimension": _STR}, "required": ["run"]}),
    "detect": ("Anomaly / change-point detection on a run.",
               {"type": "object", "properties": {"run": _STR, "metric": _STR}, "required": ["run"]}),
    "market": ("Genre/market benchmark comparison for a run.",
               {"type": "object", "properties": {"run": _STR}, "required": ["run"]}),
    "signals": ("Competitor signals for a run.",
                {"type": "object", "properties": {"run": _STR}, "required": ["run"]}),
    "synth": ("(Re)synthesize the attribution hypothesis for a run.",
              {"type": "object", "properties": {"run": _STR, "question": _STR}, "required": ["run"]}),
    "report": ("(Re)render the interactive dossier for a run.",
               {"type": "object", "properties": {"run": _STR}, "required": ["run"]}),
    "status": ("Inspect a run's state.",
               {"type": "object", "properties": {"run": _STR}, "required": ["run"]}),
    "jobs": ("List analysis runs/jobs.",
             {"type": "object", "properties": {"session": _STR}}),
    "onboard_propose": ("Propose a data profile from a CSV path (onboarding step 1).",
                        {"type": "object", "properties": {"csv": _STR, "adapter": _STR}, "required": ["csv"]}),
    "onboard_confirm": ("Confirm a proposed onboarding profile (onboarding step 2).",
                        {"type": "object", "properties": {"adapter": _STR}}),
    "profile_list": ("List onboarded game profiles.", {"type": "object", "properties": {}}),
    "profile_use": ("Switch the active game profile.",
                    {"type": "object", "properties": {"name": _STR}, "required": ["name"]}),
    "config_get": ("Read runtime config.",
                   {"type": "object", "properties": {"key": _STR}}),
    "config_set": ("Set a runtime config value.",
                   {"type": "object", "properties": {"key": _STR, "value": _STR}, "required": ["key", "value"]}),
    "doctor": ("Run environment/health diagnostics.", {"type": "object", "properties": {}}),
    "tools_list": ("List promoted (Tier-2.5) analysis tools.", {"type": "object", "properties": {}}),
    "tools_show": ("Show a promoted tool's definition.",
                   {"type": "object", "properties": {"name": _STR}, "required": ["name"]}),
    "tools_promote": ("Promote an ad-hoc script to a reusable tool.",
                      {"type": "object", "properties": {"name": _STR, "description": _STR, "script": _STR, "run": _STR},
                       "required": ["name", "description", "script"]}),
    "tools_run": ("Run a promoted tool.",
                  {"type": "object", "properties": {"name": _STR, "run": _STR, "args": {"type": "object"}},
                   "required": ["name"]}),
    "mcp_add": ("Register a new MCP tool server at runtime (admin). Provide a command (+args) or a url; env maps the server's env var names to stored secret names.",
                {"type": "object",
                 "properties": {"name": _STR, "command": _STR,
                                "args": {"type": "array", "items": _STR},
                                "url": _STR, "env": {"type": "object"}},
                 "required": ["name"]}),
    "mcp_remove": ("Unregister a previously added MCP server (admin).",
                   {"type": "object", "properties": {"name": _STR}, "required": ["name"]}),
    "mcp_list": ("List admin-registered MCP servers (admin).",
                 {"type": "object", "properties": {}}),
    "secret_set": ("Store/replace a secret value used by registered MCP servers (admin). The value is never echoed back.",
                   {"type": "object", "properties": {"name": _STR, "value": _STR},
                    "required": ["name", "value"]}),
    "secret_unset": ("Delete a stored secret (admin).",
                     {"type": "object", "properties": {"name": _STR}, "required": ["name"]}),
    "secret_list": ("List stored secret NAMES only (admin) — never values.",
                    {"type": "object", "properties": {}}),
}


def _sidecar_path(ctx) -> str | None:
    p = os.environ.get("GAA_RUN_SIDECAR")
    if p:
        return p
    try:
        cache_dir = ctx.settings.cache_dir
    except AttributeError:
        _log.warning("ctx.settings.cache_dir unavailable and GAA_RUN_SIDECAR unset; "
                     "analyze run_id sidecar not written")
        return None
    return str(Path(cache_dir) / "last_run.json")


def _record_analyze_run(ctx, result: dict) -> None:
    rid = result.get("run_id")
    if not rid:
        return
    path = _sidecar_path(ctx)
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"run_id": rid, "ts": time.time()}, f)
    os.replace(tmp, path)  # atomic


def tool_specs(*, is_admin: bool) -> list[dict]:
    """OpenAI/MCP-style specs, filtered by admin. Each: {name, description, input_schema, admin, mutating}."""
    out = []
    for name, (desc, schema) in _SPECS.items():
        admin = name in actions.ADMIN_ACTIONS
        if admin and not is_admin:
            continue
        out.append({"name": name, "description": desc, "input_schema": schema,
                    "admin": admin, "mutating": name in actions.MUTATING_ACTIONS})
    return out


def run_tool(ctx, name: str, arguments: dict, *, is_admin: bool) -> dict:
    """Validate args against the tool's schema, then dispatch via the shared action seam.
    Returns the handler's result dict, or a structured {status:error,error:...}."""
    spec = _SPECS.get(name)
    if spec is None:
        return {"status": "error", "error": f"unknown tool: {name!r}"}
    if name in actions.ADMIN_ACTIONS and not is_admin:
        return {"status": "error", "error": f"tool {name!r} requires admin context"}
    _desc, schema = spec
    try:
        jsonschema.validate(arguments or {}, schema)
    except jsonschema.ValidationError as exc:
        return {"status": "error", "error": f"invalid args for {name!r}: {exc.message}"}
    result = actions.dispatch(ctx, name, arguments or {}, is_admin=is_admin)
    # analyze returns status="done" (not "success") when the pipeline completes
    if name == "analyze" and isinstance(result, dict) and result.get("run_id"):
        _record_analyze_run(ctx, result)
    if isinstance(result, dict) and result.get("status") == "success" and name in actions.MUTATING_ACTIONS:
        try:
            persist.snapshot(ctx)
        except Exception:
            _log.exception("vStorage snapshot after %s failed", name)
    return result
