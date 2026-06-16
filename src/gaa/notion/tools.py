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

_TEXT_BLOCKS = ("paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item",
                "numbered_list_item", "to_do", "quote", "callout", "toggle", "code")

_FOCUSED_PROPS = {"since": _STR, "until": _STR, "query": _STR, "limit": _INT}

_DEFAULT_KEYWORDS = {
    "build": "release patch changelog build update liveops",
    "sentiment": "feedback sentiment review player discord",
}
_DS_ENV = {"build": "NOTION_BUILDS_DS", "sentiment": "NOTION_SENTIMENT_DS"}

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
_TAIL_HEX32 = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{32})$")


def _normalize_id(s: str) -> str:
    s = (s or "").strip()
    m = _DASHED.search(s)
    if m:
        return m.group(0).replace("-", "")
    seg = s.split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    m = _TAIL_HEX32.search(seg)
    if m:
        return m.group(1)
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
        if num is None:
            return ""
        return f"{pre}-{num}" if pre else str(num)
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


# --- helpers (Tasks 4+) --------------------------------------------------

def _blocks_to_text(blocks: list[dict]) -> str:
    parts = []
    for b in blocks:
        t = b.get("type")
        if t in _TEXT_BLOCKS:
            txt = _rich((b.get(t) or {}).get("rich_text"))
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def _row_summary(page: dict) -> dict:
    props = {k: _plain(v) for k, v in (page.get("properties") or {}).items()}
    return {"id": page.get("id"), "url": page.get("url"),
            "properties": {k: v for k, v in props.items() if v}}


# --- tool bodies (filled in Tasks 4-5) -----------------------------------

def _notion_search(client, args):
    results = client.search(args.get("query", ""), type=args.get("type"),
                            limit=int(args.get("limit") or 10))
    hits = [{"id": r.get("id"), "type": r.get("object"),
             "title": _object_title(r), "url": r.get("url")} for r in results]
    return {"status": "success", "results": hits}


def _notion_fetch(client, args):
    nid = _normalize_id(args.get("id", ""))
    page = None
    try:
        page = client.get_page(nid)
    except NotionError as exc:
        if exc.http_status not in (400, 404):
            raise
    if page is not None:
        text = _blocks_to_text(client.get_block_children(nid))
        return {"status": "success", "kind": "page", "id": nid,
                "title": _object_title(page), "url": page.get("url"), "text": text[:_MAX_TEXT]}
    ds = client.get_data_source(nid)
    rows = client.query_data_source(nid, page_size=int(args.get("limit") or 10))
    return {"status": "success", "kind": "data_source", "id": nid,
            "title": _rich(ds.get("name") or ds.get("title")), "url": ds.get("url"),
            "rows": [_row_summary(r) for r in rows]}


def _focused(client, args, *, kind):
    limit = int(args.get("limit") or 10)
    ds_id = os.environ.get(_DS_ENV[kind])
    if ds_id:
        items = _from_data_source(client, _normalize_id(ds_id), kind=kind, limit=limit)
        source = "data_source"
    else:
        items = _from_search(client, args.get("query"), kind=kind, limit=limit)
        source = "search"
    items = [it for it in items if _in_range(it.get("date"), args.get("since"), args.get("until"))]
    return {"status": "success", "source": source, "items": items[:limit]}


def _in_range(date_str, since, until) -> bool:
    if not date_str:
        return True  # never drop undated items
    d = date_str[:10]
    if since and d < since[:10]:
        return False
    if until and d > until[:10]:
        return False
    return True


def _find_prop(schema: dict, type_name: str):
    for name, meta in schema.items():
        if meta.get("type") == type_name:
            return name
    return None


def _find_named(schema: dict, needles):
    for name in schema:
        low = name.lower()
        if any(n in low for n in needles):
            return name
    return None


def _longest_rich_text(props: dict) -> str:
    best = ""
    for p in props.values():
        if p.get("type") == "rich_text":
            t = _rich(p.get("rich_text"))
            if len(t) > len(best):
                best = t
    return best


def _from_data_source(client, ds_id, *, kind, limit):
    schema = client.get_data_source(ds_id).get("properties", {})
    title_p = _find_prop(schema, "title")
    date_p = _find_prop(schema, "date")
    version_p = _find_named(schema, ("version", "build"))
    sorts = ([{"property": date_p, "direction": "descending"}] if date_p
             else [{"timestamp": "last_edited_time", "direction": "descending"}])
    rows = client.query_data_source(ds_id, sorts=sorts, page_size=max(limit, 25))
    out = []
    for row in rows:
        props = row.get("properties") or {}
        date = (_plain(props.get(date_p, {})) if date_p else "") or (row.get("created_time", "")[:10])
        summary = _longest_rich_text(props)[:_MAX_SNIPPET]
        title = _plain(props.get(title_p, {})) if title_p else ""
        if kind == "build":
            item = {"date": date, "title": title, "summary": summary, "url": row.get("url")}
            if version_p:
                item["version"] = _plain(props.get(version_p, {}))
        else:
            item = {"date": date, "source": title or None, "snippet": summary, "url": row.get("url")}
        out.append(item)
    return out


def _from_search(client, query, *, kind, limit):
    q = " ".join(x for x in (_DEFAULT_KEYWORDS[kind], query or "") if x).strip()
    results = client.search(q, type="page", limit=max(limit, 10))
    out = []
    for r in results[:max(limit, 5)]:
        date = (r.get("created_time") or r.get("last_edited_time") or "")[:10]
        for p in (r.get("properties") or {}).values():
            if p.get("type") == "date" and _plain(p):
                date = _plain(p)[:10]
                break
        snippet = _blocks_to_text(client.get_block_children(r.get("id")))[:_MAX_SNIPPET]
        if kind == "build":
            out.append({"date": date, "title": _object_title(r), "summary": snippet, "url": r.get("url")})
        else:
            out.append({"date": date, "source": _object_title(r) or None, "snippet": snippet, "url": r.get("url")})
    return out
