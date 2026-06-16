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
from gaa.sensortower import guard as _st_guard, cache as _st_cache, relay as _st_relay_mod, appids as _st_appids
from gaa.appstore import search as _appstore

_log = logging.getLogger(__name__)

_STR = {"type": "string"}

_ST_DATA_SCHEMA = {"type": "object", "properties": {
    "app_ids": {"type": "array", "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
    "labels": {"type": "array", "items": _STR},
    "start_date": _STR, "end_date": _STR,
    "countries": {"type": "array", "items": _STR},
    "metrics": {"type": "array", "items": _STR},
    "refresh": {"type": "boolean"}}}

_ST_TOOL_KEYS = {"st_app_performance", "st_unified_app_performance", "st_download_channel",
                 "st_app_store", "st_search_optimization"}


def _st_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _st_relay(built: dict) -> dict:
    return _st_relay_mod.request(built)


def _st_resolver_for(ctx):
    prof = ctx.profiles.get_active()
    name = prof.name if prof else "__none__"
    return lambda label: _st_appids.resolve(ctx.settings.db_path, name, label)


def _appstore_search(query: str, country: str, limit: int) -> list[dict]:
    return _appstore.search_apps(query, country=country, limit=limit)


def _run_st_tool(ctx, name: str, args: dict) -> dict:
    if name == "st_set_app_id":
        prof = ctx.profiles.get_active()
        if not prof:
            return {"status": "error", "error": "no_active_profile"}
        _st_appids.set_app_id(ctx.settings.db_path, prof.name, args["label"], args["id"], args.get("id_type", "app_id"))
        return {"status": "success", "label": args["label"]}
    built_out = _st_guard.build(name, args, resolver=_st_resolver_for(ctx), today=_st_today())
    if built_out.get("status") == "error":
        return built_out  # need_app_id / bad_date
    built = built_out["built"]
    key = _st_cache.make_key(built)
    if not args.get("refresh"):
        hit = _st_cache.get(key, now=time.time())
        if hit is not None:
            return {"data": hit, "cached": True, "scope_trimmed": built_out.get("scope_trimmed", [])}
    out = _st_relay(built)
    if "error" in out:
        kind = out["error"].get("kind", "upstream_error")
        r = {"status": "error", "error": kind}
        if out["error"].get("detail"):
            r["detail"] = out["error"]["detail"]
        return r
    data = out["result"]
    _st_cache.put(key, data, end_date=built["params"]["end_date"], now=time.time())
    return {"data": data, "cached": False, "scope_trimmed": built_out.get("scope_trimmed", [])}

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
    "st_app_performance": ("Sensor Tower app downloads/revenue/active-users/retention/engagement for one or more games (app_ids and/or profile labels).", _ST_DATA_SCHEMA),
    "st_unified_app_performance": ("Sensor Tower cross-platform unified app performance.", _ST_DATA_SCHEMA),
    "st_download_channel": ("Sensor Tower organic-vs-paid download attribution.", _ST_DATA_SCHEMA),
    "st_app_store": ("Sensor Tower app-store ranks/ratings/reviews.", _ST_DATA_SCHEMA),
    "st_search_optimization": ("Sensor Tower ASO: keyword rank/difficulty/visibility (supports a `keyword` list).",
                               {"type": "object", "properties": {**_ST_DATA_SCHEMA["properties"], "keyword": {"type": "array", "items": _STR}}}),
    "st_set_app_id": ("Remember a Sensor Tower app id under a label on the active game profile (e.g. label 'self' or 'competitor:clash').",
                      {"type": "object", "properties": {"label": _STR, "id": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "id_type": _STR}, "required": ["label", "id"]}),
    "appstore_search": ("Find apps by name or genre on the public App Store. Returns candidates each with an `app_id` (= the Sensor Tower iOS app id), name, publisher, genre. Use this to turn a game name or genre into an app_id, then pass that id to the st_* tools (and st_set_app_id to remember it).",
                        {"type": "object",
                         "properties": {"query": _STR, "country": _STR, "limit": {"type": "integer"}},
                         "required": ["query"]}),
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
    if name in _ST_TOOL_KEYS or name == "st_set_app_id":
        result = _run_st_tool(ctx, name, arguments or {})
        if name == "st_set_app_id" and isinstance(result, dict) and result.get("status") == "success":
            try:
                persist.snapshot(ctx)
            except Exception:
                _log.exception("vStorage snapshot after st_set_app_id failed")
        return result
    if name == "appstore_search":
        a = arguments or {}
        try:
            apps = _appstore_search(a["query"], a.get("country", "US"), a.get("limit", 8))
        except Exception as exc:
            _log.exception("appstore_search failed")
            return {"status": "error", "error": "appstore_unavailable", "detail": str(exc)}
        return {"apps": apps}
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


