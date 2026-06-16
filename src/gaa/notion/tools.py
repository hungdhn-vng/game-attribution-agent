"""Notion read tools exposed over MCP. Framework-free; no gaa.core import.

Four read-only tools (build_updates, user_sentiment, notion_search, notion_fetch)
over Notion's data-source model. run_tool validates args, guards the token,
dispatches, and maps NotionError to a structured {status:"error", ...} result so
the stdio loop never crashes.
"""
from __future__ import annotations

import os
import re

import jsonschema

from gaa.notion.client import NotionClient, NotionError

_STR = {"type": "string"}
_INT = {"type": "integer"}
_MAX_TEXT = 2000
_MAX_SNIPPET = 500

_FOCUSED_PROPS = {"since": _STR, "until": _STR, "query": _STR, "limit": _INT}

_SPECS: dict[str, tuple[str, dict]] = {
    "build_updates": (
        "Recent build/release/liveops updates from Notion. Queries the configured Builds "
        "data source if set (NOTION_BUILDS_DS), else searches the workspace. Optional "
        "since/until are ISO dates (YYYY-MM-DD); query adds keywords; limit caps results.",
        {"type": "object", "properties": dict(_FOCUSED_PROPS), "required": []}),
    "user_sentiment": (
        "Recent user/player sentiment and feedback items from Notion. Queries the "
        "configured Sentiment data source if set (NOTION_SENTIMENT_DS), else searches the "
        "workspace. Returns raw items (not scored); full report text may be in the page "
        "body (use notion_fetch on an item url/id). since/until are ISO dates.",
        {"type": "object", "properties": dict(_FOCUSED_PROPS), "required": []}),
    "notion_search": (
        "Search the Notion workspace for pages or data sources by free text.",
        {"type": "object",
         "properties": {"query": _STR,
                        "type": {"type": "string", "enum": ["page", "data_source"]},
                        "limit": _INT},
         "required": ["query"]}),
    "notion_fetch": (
        "Fetch a Notion page (text) or data source (rows) by id or URL.",
        {"type": "object", "properties": {"id": _STR}, "required": ["id"]}),
}


def tool_specs() -> list[dict]:
    return [{"name": n, "description": d, "input_schema": s} for n, (d, s) in _SPECS.items()]


def _client_factory(token: str) -> NotionClient:
    """Seam so tests can inject a MockTransport-backed client."""
    return NotionClient(token)


def run_tool(name: str, arguments: dict) -> dict:
    spec = _SPECS.get(name)
    if spec is None:
        return {"status": "error", "error": f"unknown tool: {name!r}"}
    try:
        jsonschema.validate(arguments or {}, spec[1])
    except jsonschema.ValidationError as exc:
        return {"status": "error", "error": f"invalid args for {name!r}: {exc.message}"}
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        return {"status": "error", "error": "notion token not configured"}
    client = _client_factory(token)
    args = arguments or {}
    try:
        if name == "notion_search":
            return _notion_search(client, args)
        if name == "notion_fetch":
            return _notion_fetch(client, args)
        if name == "build_updates":
            return _focused(client, args, kind="build")
        if name == "user_sentiment":
            return _focused(client, args, kind="sentiment")
        return {"status": "error", "error": f"unhandled tool: {name!r}"}
    except NotionError as exc:
        out = {"status": "error", "error": exc.message, "http_status": exc.http_status}
        if exc.retry_after is not None:
            out["retry_after"] = exc.retry_after
        return out
    except Exception as exc:  # never crash the stdio loop
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


# --- helpers -------------------------------------------------------------

_DASHED = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX32 = re.compile(r"[0-9a-fA-F]{32}")


def _normalize_id(s: str) -> str:
    s = (s or "").strip()
    m = _DASHED.search(s)
    if m:
        return m.group(0).replace("-", "")
    m = _HEX32.search(s.replace("-", ""))
    if m:
        return m.group(0)
    return s


def _rich(arr) -> str:
    """Join Notion rich-text / name arrays to plain text (plain_text, else text.content)."""
    out = []
    for x in (arr or []):
        out.append(x.get("plain_text") or (x.get("text") or {}).get("content") or "")
    return "".join(out)


def _plain(prop: dict) -> str:
    t = (prop or {}).get("type")
    if t == "title":
        return _rich(prop.get("title"))
    if t == "rich_text":
        return _rich(prop.get("rich_text"))
    if t == "date":
        return (prop.get("date") or {}).get("start") or ""
    if t == "select":
        return (prop.get("select") or {}).get("name") or ""
    if t == "status":
        return (prop.get("status") or {}).get("name") or ""
    if t == "multi_select":
        return ", ".join(o.get("name", "") for o in (prop.get("multi_select") or []))
    if t in ("created_time", "last_edited_time"):
        return prop.get(t) or ""
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if t == "checkbox":
        return "true" if prop.get("checkbox") else ""
    if t == "url":
        return prop.get("url") or ""
    if t == "unique_id":
        u = prop.get("unique_id") or {}
        pre, num = u.get("prefix"), u.get("number")
        return f"{pre}-{num}" if pre else ("" if num is None else str(num))
    if t == "people":
        return ", ".join(p.get("name", "") for p in (prop.get("people") or []))
    return ""


def _object_title(obj: dict) -> str:
    o = obj.get("object")
    if o == "data_source":
        return _rich(obj.get("name") or obj.get("title"))
    if o == "database":
        return _rich(obj.get("title"))
    for p in (obj.get("properties") or {}).values():
        if p.get("type") == "title":
            return _rich(p.get("title"))
    return ""


# --- tool bodies (filled in Tasks 4-5) -----------------------------------

def _notion_search(client, args):
    # Stub: invoke the client so NotionError propagates; full body in Task 4.
    client.search(args.get("query", ""), type=args.get("type"), limit=args.get("limit", 10))
    return {"status": "error", "error": "not implemented"}


def _notion_fetch(client, args):
    return {"status": "error", "error": "not implemented"}


def _focused(client, args, *, kind):
    return {"status": "error", "error": "not implemented"}
