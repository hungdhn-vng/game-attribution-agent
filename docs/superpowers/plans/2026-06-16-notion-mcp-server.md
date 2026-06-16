# Notion MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, read-only `gaa.notion` stdio MCP server exposing four tools (`build_updates`, `user_sentiment`, `notion_search`, `notion_fetch`) that the GAA agent connects to at runtime via the existing admin `secret_set` + `mcp_add` path.

**Architecture:** A self-contained `src/gaa/notion/` module — `client.py` (httpx wrapper over the Notion REST API), `tools.py` (specs + dispatch + result shaping), `server.py` (stdio MCP adapter) — that never imports `gaa.core`. Focused tools resolve their source flexibly: structured **data-source** query when `NOTION_BUILDS_DS`/`NOTION_SENTIMENT_DS` is configured, keyword-search fallback otherwise. Mirrors the existing `gaa.mcp` server shape exactly.

**Tech Stack:** Python 3.11, `httpx` (core dep), `mcp` SDK (server extra), `jsonschema` (server extra), `pytest`. **Notion REST API with `Notion-Version: 2025-09-03` (data-source model)** — query `POST /v1/data_sources/{id}/query`, schema `GET /v1/data_sources/{id}`, `POST /v1/search`, `GET /v1/pages/{id}`, `GET /v1/blocks/{id}/children`.

**Spec:** `docs/superpowers/specs/2026-06-16-notion-mcp-server-design.md` (read its **"Live recon corrections (2026-06-16)"** section — the data-source model is load-bearing).

> **Why data sources, not databases:** a live probe of the target workspace showed it uses
> Notion's new data-source model. The IDs are data-source IDs; `2022-06-28`
> `/databases/{id}/query` returns 404. Validated real schemas:
> `04_LiveOps Calendar Content` (title=`Event Name`, date=`Go-live Date`, text=`Brief`) and
> `10_Discord Sentiment` (title=`Report`, text=`note`, no date → `created_time`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/gaa/notion/__init__.py` | Empty package marker |
| `src/gaa/notion/client.py` | `NotionClient` + `NotionError`: HTTP plumbing, auth headers (`Notion-Version: 2025-09-03`), the 5 endpoints, error surfacing. |
| `src/gaa/notion/tools.py` | `_SPECS`, `tool_specs()`, `run_tool()`, result-shaping helpers. Delegates all I/O to `client`. |
| `src/gaa/notion/server.py` | stdio MCP adapter (`build_server`, `_for_test_handles`, `main`). |
| `tests/notion/__init__.py` | Empty test-package marker |
| `tests/notion/conftest.py` | Shared `make_client(handler)` + `mock_tools(monkeypatch, handler)` helpers |
| `tests/notion/test_client.py` | Client request shaping + endpoints + error surfacing |
| `tests/notion/test_tools_generic.py` | `tool_specs`, validation, missing-token, error mapping, `notion_search`, `notion_fetch`, id/text helpers |
| `tests/notion/test_tools_focused.py` | `build_updates`/`user_sentiment` structured + fallback paths |
| `tests/notion/test_server.py` | MCP adapter list/call round-trip |
| `docs/spikes/notion-api-shapes.md` | Manual live spike (gated, not CI) |
| `docs/notion-connect.md` | Operator runbook: the `secret_set` + `mcp_add` recipe |

**Test command (this worktree):** `.venv/bin/python -m pytest tests/notion -q` (run from the worktree root). The full suite (`.venv/bin/python -m pytest -q`) takes ~2 min and has a 415-test green baseline.

---

## Task 1: NotionClient core (`_request`, `search`, errors)

**Files:**
- Create: `src/gaa/notion/__init__.py` (empty)
- Create: `src/gaa/notion/client.py`
- Create: `tests/notion/__init__.py` (empty)
- Create: `tests/notion/conftest.py`
- Test: `tests/notion/test_client.py`

- [ ] **Step 1: Create the empty package markers**

```bash
mkdir -p src/gaa/notion tests/notion
: > src/gaa/notion/__init__.py
: > tests/notion/__init__.py
```

- [ ] **Step 2: Write the shared test helper**

Create `tests/notion/conftest.py`:

```python
import httpx
import pytest

from gaa.notion.client import NotionClient


def make_client(handler, token="ntn_test"):
    """A NotionClient whose HTTP layer is an httpx MockTransport routed by `handler`.

    `handler` is a callable (httpx.Request) -> httpx.Response.
    """
    transport = httpx.MockTransport(handler)
    return NotionClient(token, http=httpx.Client(transport=transport))


@pytest.fixture
def make_client_fixture():
    return make_client
```

- [ ] **Step 3: Write the failing test**

Create `tests/notion/test_client.py`:

```python
import httpx
import pytest

from gaa.notion.client import NotionClient, NotionError
from tests.notion.conftest import make_client


def test_search_sends_auth_version_and_returns_results():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["version"] = request.headers.get("Notion-Version")
        return httpx.Response(200, json={"results": [{"id": "p1", "object": "page"}]})

    client = make_client(handler)
    results = client.search("patch notes", type="page", limit=5)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.notion.com/v1/search"
    assert captured["auth"] == "Bearer ntn_test"
    assert captured["version"] == "2025-09-03"
    assert results == [{"id": "p1", "object": "page"}]


def test_http_error_raises_notion_error_with_status():
    def handler(request):
        return httpx.Response(404, json={"object": "error", "code": "object_not_found",
                                         "message": "Could not find data source"})

    client = make_client(handler)
    with pytest.raises(NotionError) as exc:
        client.search("x")
    assert exc.value.http_status == 404
    assert "Could not find data source" in exc.value.message


def test_rate_limit_surfaces_retry_after():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "30"}, json={})

    client = make_client(handler)
    with pytest.raises(NotionError) as exc:
        client.search("x")
    assert exc.value.http_status == 429
    assert exc.value.retry_after == 30.0
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/notion/test_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.notion.client'`

- [ ] **Step 5: Write the minimal implementation**

Create `src/gaa/notion/client.py`:

```python
"""Thin httpx wrapper over the Notion REST API (data-source model, v2025-09-03). Read-only.

Knows HTTP + Notion; nothing about MCP or tool shaping. All failures raise
NotionError carrying http_status (and retry_after for 429) so the tools layer
can map them to structured results.
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://api.notion.com/v1"
_VERSION = "2025-09-03"


class NotionError(Exception):
    def __init__(self, message: str, *, http_status: int | None = None,
                 retry_after: float | None = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after


class NotionClient:
    def __init__(self, token: str, *, http: httpx.Client | None = None, timeout: float = 30.0):
        self._token = token
        self._http = http or httpx.Client(timeout=timeout)

    def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": _VERSION,
            "Content-Type": "application/json",
        }
        resp = self._http.request(method, f"{_BASE_URL}{path}", headers=headers, json=json)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            raise NotionError("notion rate limited", http_status=429,
                              retry_after=float(ra) if ra else None)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("message") or body.get("code") or resp.text
            except Exception:
                msg = resp.text
            raise NotionError(msg, http_status=resp.status_code)
        return resp.json()

    def search(self, query: str, *, type: str | None = None, limit: int = 10) -> list[dict]:
        body: dict = {"query": query or "", "page_size": min(int(limit or 10), 100)}
        if type in ("page", "data_source"):
            body["filter"] = {"value": type, "property": "object"}
        return self._request("POST", "/search", json=body).get("results", [])
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/notion/test_client.py -q`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add src/gaa/notion/__init__.py src/gaa/notion/client.py tests/notion/
git commit -m "feat(notion): NotionClient core — request plumbing, search, error surfacing"
```

---

## Task 2: NotionClient remaining endpoints (data sources, pages, blocks)

**Files:**
- Modify: `src/gaa/notion/client.py` (add 4 methods)
- Test: `tests/notion/test_client.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/notion/test_client.py`:

```python
def test_get_data_source_query_page_and_blocks():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path == "/v1/data_sources/ds1":
            return httpx.Response(200, json={"id": "ds1", "properties": {"Name": {"type": "title"}}})
        if path == "/v1/data_sources/ds1/query":
            return httpx.Response(200, json={"results": [{"id": "row1"}]})
        if path == "/v1/pages/pg1":
            return httpx.Response(200, json={"id": "pg1", "object": "page"})
        if path == "/v1/blocks/pg1/children":
            return httpx.Response(200, json={"results": [{"type": "paragraph"}]})
        return httpx.Response(500, json={})

    client = make_client(handler)
    assert client.get_data_source("ds1")["id"] == "ds1"
    assert client.query_data_source("ds1", page_size=5) == [{"id": "row1"}]
    assert client.get_page("pg1")["object"] == "page"
    assert client.get_block_children("pg1") == [{"type": "paragraph"}]
    assert ("POST", "/v1/data_sources/ds1/query") in seen
    assert ("GET", "/v1/blocks/pg1/children") in seen


def test_query_data_source_passes_sorts():
    captured = {}

    def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    client = make_client(handler)
    client.query_data_source("ds1", sorts=[{"property": "Go-live Date", "direction": "descending"}],
                             page_size=25)
    assert captured["body"]["sorts"] == [{"property": "Go-live Date", "direction": "descending"}]
    assert captured["body"]["page_size"] == 25
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/notion/test_client.py -q`
Expected: FAIL — `AttributeError: 'NotionClient' object has no attribute 'get_data_source'`

- [ ] **Step 3: Add the methods**

Append to the `NotionClient` class in `src/gaa/notion/client.py`:

```python
    def get_data_source(self, ds_id: str) -> dict:
        return self._request("GET", f"/data_sources/{ds_id}")

    def query_data_source(self, ds_id: str, *, sorts: list | None = None,
                          page_size: int = 10) -> list[dict]:
        body: dict = {"page_size": min(int(page_size or 10), 100)}
        if sorts:
            body["sorts"] = sorts
        return self._request("POST", f"/data_sources/{ds_id}/query", json=body).get("results", [])

    def get_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{page_id}")

    def get_block_children(self, block_id: str, *, page_size: int = 50) -> list[dict]:
        ps = min(int(page_size or 50), 100)
        return self._request("GET", f"/blocks/{block_id}/children?page_size={ps}").get("results", [])
```

- [ ] **Step 4: Run to verify passing**

Run: `.venv/bin/python -m pytest tests/notion/test_client.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/notion/client.py tests/notion/test_client.py
git commit -m "feat(notion): client get_data_source/query_data_source/get_page/get_block_children"
```

---

## Task 3: tools.py plumbing — specs, dispatch, validation, helpers

**Files:**
- Create: `src/gaa/notion/tools.py`
- Test: `tests/notion/test_tools_generic.py`

This task builds `_SPECS`, `tool_specs()`, the `run_tool()` dispatch shell (validation + missing-token guard + `NotionError` mapping), and the shared helpers (`_normalize_id`, `_rich`, `_plain`, `_object_title`). The four tool bodies are stubbed to `{"status": "error", "error": "not implemented"}` and filled in Tasks 4–5.

- [ ] **Step 1: Extend the test helper for tools-level mocking**

Append to `tests/notion/conftest.py`:

```python
def mock_tools(monkeypatch, handler, *, env=None):
    """Point gaa.notion.tools at a MockTransport-backed client and set NOTION_TOKEN.

    `env` extra vars (e.g. NOTION_BUILDS_DS) are set too.
    """
    from gaa.notion import tools
    monkeypatch.setenv("NOTION_TOKEN", "ntn_test")
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(tools, "_client_factory", lambda token: make_client(handler, token))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/notion/test_tools_generic.py`:

```python
import httpx

from gaa.notion import tools
from tests.notion.conftest import mock_tools


def test_tool_specs_are_the_four_read_tools():
    names = {t["name"] for t in tools.tool_specs()}
    assert names == {"build_updates", "user_sentiment", "notion_search", "notion_fetch"}
    for t in tools.tool_specs():
        assert t["input_schema"]["type"] == "object"


def test_notion_search_type_enum_is_page_or_data_source():
    spec = {t["name"]: t for t in tools.tool_specs()}["notion_search"]
    assert spec["input_schema"]["properties"]["type"]["enum"] == ["page", "data_source"]


def test_unknown_tool_is_structured_error():
    assert tools.run_tool("nope", {})["status"] == "error"


def test_missing_token_is_structured_error(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    out = tools.run_tool("notion_search", {"query": "x"})
    assert out == {"status": "error", "error": "notion token not configured"}


def test_invalid_args_rejected_by_schema(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "ntn_test")
    out = tools.run_tool("notion_search", {})  # query is required
    assert out["status"] == "error"
    assert "invalid args" in out["error"]


def test_notion_error_is_mapped_to_structured_result(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"object": "error", "code": "unauthorized",
                                         "message": "API token is invalid."})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_search", {"query": "x"})
    assert out["status"] == "error"
    assert out["http_status"] == 401
    assert "invalid" in out["error"]


def test_normalize_id_extracts_from_url():
    assert tools._normalize_id(
        "https://app.notion.com/p/Event-37c0e4e2394280938d60defc532e5ad8"
    ) == "37c0e4e2394280938d60defc532e5ad8"
    assert tools._normalize_id(
        "abee2267-021c-4a98-b91b-95d71e2a0cee"
    ) == "abee2267021c4a98b91b95d71e2a0cee"
    assert tools._normalize_id("plainid") == "plainid"


def test_plain_extracts_common_property_types():
    assert tools._plain({"type": "title", "title": [{"plain_text": "Hi"}]}) == "Hi"
    assert tools._plain({"type": "rich_text", "rich_text": [{"plain_text": "a"}, {"plain_text": "b"}]}) == "ab"
    assert tools._plain({"type": "date", "date": {"start": "2026-05-01"}}) == "2026-05-01"
    assert tools._plain({"type": "select", "select": {"name": "Q3 2026"}}) == "Q3 2026"
    assert tools._plain({"type": "status", "status": {"name": "Not started"}}) == "Not started"
    assert tools._plain({"type": "multi_select",
                         "multi_select": [{"name": "PC"}, {"name": "Mobile"}]}) == "PC, Mobile"
    assert tools._plain({"type": "created_time", "created_time": "2026-06-15T02:06:00.000Z"}) == "2026-06-15T02:06:00.000Z"
    assert tools._plain({"type": "number", "number": 7}) == "7"
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/notion/test_tools_generic.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.notion.tools'`

- [ ] **Step 4: Write the implementation (plumbing + helpers + stubs)**

Create `src/gaa/notion/tools.py`:

```python
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
    return {"status": "error", "error": "not implemented"}


def _notion_fetch(client, args):
    return {"status": "error", "error": "not implemented"}


def _focused(client, args, *, kind):
    return {"status": "error", "error": "not implemented"}
```

- [ ] **Step 5: Run to verify passing**

Run: `.venv/bin/python -m pytest tests/notion/test_tools_generic.py -q`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add src/gaa/notion/tools.py tests/notion/conftest.py tests/notion/test_tools_generic.py
git commit -m "feat(notion): tools plumbing — specs, dispatch, validation, helpers"
```

---

## Task 4: notion_search + notion_fetch

**Files:**
- Modify: `src/gaa/notion/tools.py` (`_notion_search`, `_notion_fetch`, add `_blocks_to_text`, `_row_summary`)
- Test: `tests/notion/test_tools_generic.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/notion/test_tools_generic.py`:

```python
def test_notion_search_shapes_hits(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"object": "page", "id": "p1", "url": "https://n/p1",
             "properties": {"Event Name": {"type": "title", "title": [{"plain_text": "Patch 1.2"}]}}},
            {"object": "data_source", "id": "d1", "url": "https://n/d1",
             "name": [{"plain_text": "Releases"}]},
        ]})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_search", {"query": "patch"})
    assert out["status"] == "success"
    assert out["results"][0] == {"id": "p1", "type": "page", "title": "Patch 1.2", "url": "https://n/p1"}
    assert out["results"][1]["title"] == "Releases"
    assert out["results"][1]["type"] == "data_source"


def test_notion_fetch_page_returns_text(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/pages/abc":
            return httpx.Response(200, json={"object": "page", "id": "abc", "url": "https://n/abc",
                                             "properties": {"Event Name": {"type": "title",
                                                                           "title": [{"plain_text": "Notes"}]}}})
        if path == "/v1/blocks/abc/children":
            return httpx.Response(200, json={"results": [
                {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Build 5"}]}},
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Fixed crash."}]}},
            ]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_fetch", {"id": "abc"})
    assert out["status"] == "success"
    assert out["kind"] == "page"
    assert out["title"] == "Notes"
    assert out["text"] == "Build 5\nFixed crash."


def test_notion_fetch_falls_back_to_data_source(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/pages/ds9":
            return httpx.Response(404, json={"object": "error", "code": "object_not_found",
                                             "message": "Could not find page"})
        if path == "/v1/data_sources/ds9":
            return httpx.Response(200, json={"id": "ds9", "url": "https://n/ds9",
                                             "name": [{"plain_text": "Feedback"}]})
        if path == "/v1/data_sources/ds9/query":
            return httpx.Response(200, json={"results": [
                {"id": "r1", "url": "https://n/r1",
                 "properties": {"note": {"type": "rich_text", "rich_text": [{"plain_text": "great"}]}}},
            ]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_fetch", {"id": "ds9"})
    assert out["status"] == "success"
    assert out["kind"] == "data_source"
    assert out["title"] == "Feedback"
    assert out["rows"][0]["properties"]["note"] == "great"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/notion/test_tools_generic.py -k "search_shapes or fetch" -q`
Expected: FAIL — assertions hit the `"not implemented"` stubs.

- [ ] **Step 3: Implement the two tool bodies + block/row helpers**

In `src/gaa/notion/tools.py`, replace the `_notion_search` and `_notion_fetch` stubs and add the helpers:

```python
_TEXT_BLOCKS = ("paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item",
                "numbered_list_item", "to_do", "quote", "callout", "toggle", "code")


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
```

- [ ] **Step 4: Run to verify passing**

Run: `.venv/bin/python -m pytest tests/notion/test_tools_generic.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/notion/tools.py tests/notion/test_tools_generic.py
git commit -m "feat(notion): notion_search + notion_fetch (page text / data-source rows)"
```

---

## Task 5: build_updates + user_sentiment (structured + fallback)

**Files:**
- Modify: `src/gaa/notion/tools.py` (`_focused` + `_from_data_source`, `_from_search`, `_in_range`, `_find_prop`, `_find_named`, `_longest_rich_text`)
- Test: `tests/notion/test_tools_focused.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/notion/test_tools_focused.py` (schemas mirror the real `04_LiveOps Calendar Content` and `10_Discord Sentiment` data sources):

```python
import httpx

from gaa.notion import tools
from tests.notion.conftest import mock_tools


def test_build_updates_structured_data_source_path(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/data_sources/buildsds":
            return httpx.Response(200, json={"name": [{"plain_text": "04_LiveOps Calendar Content"}],
                                             "properties": {
                                                 "Event Name": {"type": "title"},
                                                 "Go-live Date": {"type": "date"},
                                                 "Version": {"type": "rich_text"},
                                                 "Brief": {"type": "rich_text"},
                                             }})
        if path == "/v1/data_sources/buildsds/query":
            return httpx.Response(200, json={"results": [
                {"url": "https://n/r1", "created_time": "2026-05-10T00:00:00.000Z",
                 "properties": {
                     "Event Name": {"type": "title", "title": [{"plain_text": "Spring patch"}]},
                     "Go-live Date": {"type": "date", "date": {"start": "2026-05-10"}},
                     "Version": {"type": "rich_text", "rich_text": [{"plain_text": "1.2"}]},
                     "Brief": {"type": "rich_text", "rich_text": [{"plain_text": "Big balance changes and bugfixes"}]},
                 }},
            ]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler, env={"NOTION_BUILDS_DS": "buildsds"})
    out = tools.run_tool("build_updates", {"since": "2026-05-01", "until": "2026-05-31"})
    assert out["status"] == "success"
    assert out["source"] == "data_source"
    item = out["items"][0]
    assert item["date"] == "2026-05-10"
    assert item["title"] == "Spring patch"
    assert item["version"] == "1.2"
    assert "balance" in item["summary"]


def test_build_updates_date_filter_excludes_out_of_range(monkeypatch):
    def handler(request):
        if request.url.path == "/v1/data_sources/buildsds":
            return httpx.Response(200, json={"properties": {
                "Event Name": {"type": "title"}, "Go-live Date": {"type": "date"}}})
        return httpx.Response(200, json={"results": [
            {"url": "u1", "properties": {"Event Name": {"type": "title", "title": [{"plain_text": "old"}]},
                                         "Go-live Date": {"type": "date", "date": {"start": "2026-01-01"}}}},
            {"url": "u2", "properties": {"Event Name": {"type": "title", "title": [{"plain_text": "new"}]},
                                         "Go-live Date": {"type": "date", "date": {"start": "2026-05-15"}}}},
        ]})
    mock_tools(monkeypatch, handler, env={"NOTION_BUILDS_DS": "buildsds"})
    out = tools.run_tool("build_updates", {"since": "2026-05-01"})
    titles = [i["title"] for i in out["items"]]
    assert titles == ["new"]


def test_user_sentiment_no_date_prop_uses_created_time(monkeypatch):
    """Mirrors 10_Discord Sentiment: title=Report, text=note, NO date property."""
    def handler(request):
        path = request.url.path
        if path == "/v1/data_sources/sentds":
            return httpx.Response(200, json={"name": [{"plain_text": "10_Discord Sentiment"}],
                                             "properties": {
                                                 "Report": {"type": "title"},
                                                 "note": {"type": "rich_text"},
                                                 "Created time": {"type": "created_time"}}})
        return httpx.Response(200, json={"results": [
            {"url": "https://n/s1", "created_time": "2026-06-15T02:06:00.000Z",
             "properties": {
                 "Report": {"type": "title", "title": [{"plain_text": "Week 25 sentiment"}]},
                 "note": {"type": "rich_text", "rich_text": [{"plain_text": "Players love the new map"}]}}}]})
    mock_tools(monkeypatch, handler, env={"NOTION_SENTIMENT_DS": "sentds"})
    out = tools.run_tool("user_sentiment", {})
    assert out["status"] == "success"
    assert out["source"] == "data_source"
    item = out["items"][0]
    assert item["date"] == "2026-06-15"        # fell back to created_time
    assert item["source"] == "Week 25 sentiment"
    assert "love" in item["snippet"]


def test_user_sentiment_search_fallback_when_no_db(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/search":
            return httpx.Response(200, json={"results": [
                {"object": "page", "id": "p1", "url": "https://n/p1",
                 "created_time": "2026-05-09T00:00:00.000Z",
                 "properties": {"Report": {"type": "title", "title": [{"plain_text": "Reddit thread"}]}}},
            ]})
        if path == "/v1/blocks/p1/children":
            return httpx.Response(200, json={"results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Players love the new map."}]}}]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler)  # no NOTION_SENTIMENT_DS
    out = tools.run_tool("user_sentiment", {})
    assert out["status"] == "success"
    assert out["source"] == "search"
    item = out["items"][0]
    assert item["date"] == "2026-05-09"
    assert item["source"] == "Reddit thread"
    assert "love" in item["snippet"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/notion/test_tools_focused.py -q`
Expected: FAIL — `_focused` returns the `"not implemented"` stub.

- [ ] **Step 3: Implement `_focused` and its helpers**

In `src/gaa/notion/tools.py`, replace the `_focused` stub and add helpers:

```python
_DEFAULT_KEYWORDS = {
    "build": "release patch changelog build update liveops",
    "sentiment": "feedback sentiment review player discord",
}
_DS_ENV = {"build": "NOTION_BUILDS_DS", "sentiment": "NOTION_SENTIMENT_DS"}


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
```

- [ ] **Step 4: Run to verify passing**

Run: `.venv/bin/python -m pytest tests/notion/test_tools_focused.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/notion/tools.py tests/notion/test_tools_focused.py
git commit -m "feat(notion): build_updates + user_sentiment (structured data source + search fallback)"
```

---

## Task 6: stdio MCP server adapter

**Files:**
- Create: `src/gaa/notion/server.py`
- Test: `tests/notion/test_server.py`

- [ ] **Step 1: Write the failing test**

Create `tests/notion/test_server.py`:

```python
import json

from gaa.notion import server


def test_build_server_lists_four_tools_and_calls(monkeypatch):
    monkeypatch.setattr(server.tools, "run_tool",
                        lambda name, args: {"status": "success", "echo": {"name": name, "args": args}})
    srv, listed, called = server._for_test_handles()
    names = {t.name for t in listed()}
    assert names == {"build_updates", "user_sentiment", "notion_search", "notion_fetch"}
    out = called("notion_search", {"query": "x"})
    assert json.loads(out[0].text) == {"status": "success",
                                       "echo": {"name": "notion_search", "args": {"query": "x"}}}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/notion/test_server.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.notion.server'`

- [ ] **Step 3: Implement the adapter (mirrors `gaa/mcp/server.py`)**

Create `src/gaa/notion/server.py`:

```python
"""stdio MCP adapter for the Notion read tools. Mirrors gaa.mcp.server.

Entry point: python -m gaa.notion.server
"""
from __future__ import annotations

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from gaa.notion import tools


def build_server() -> Server:
    srv = Server("notion")

    @srv.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
            for t in tools.tool_specs()
        ]

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = tools.run_tool(name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result))]

    return srv


def _for_test_handles():
    """Expose registered list/call handlers synchronously for unit tests
    (mcp 1.27.x: handlers in srv.request_handlers; results unwrap via .root)."""
    srv = build_server()

    def listed() -> list[types.Tool]:
        req = types.ListToolsRequest(method="tools/list")
        return asyncio.run(srv.request_handlers[types.ListToolsRequest](req)).root.tools

    def called(name: str, args: dict) -> list[types.TextContent]:
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=args),
        )
        return asyncio.run(srv.request_handlers[types.CallToolRequest](req)).root.content

    return srv, listed, called


def main() -> None:
    srv = build_server()

    async def _run():
        async with stdio_server() as (read, write):
            await srv.run(read, write, srv.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify passing**

Run: `.venv/bin/python -m pytest tests/notion/test_server.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/notion/server.py tests/notion/test_server.py
git commit -m "feat(notion): stdio MCP server adapter (python -m gaa.notion.server)"
```

---

## Task 7: Full-suite green + import/launch sanity

**Files:** none (verification task)

- [ ] **Step 1: Run the whole notion suite**

Run: `.venv/bin/python -m pytest tests/notion -q`
Expected: PASS (~19 passed)

- [ ] **Step 2: Run the whole repo suite (no regressions)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — the prior green count (415) **plus** the new notion tests; 0 failures. (~2 min.)

- [ ] **Step 3: Confirm the module imports and the entry point is launchable**

Run:
```bash
.venv/bin/python -c "import gaa.notion.client, gaa.notion.tools, gaa.notion.server; print('import ok')"
.venv/bin/python -c "from gaa.notion import tools; print(sorted(t['name'] for t in tools.tool_specs()))"
```
Expected: `import ok` then `['build_updates', 'notion_fetch', 'notion_search', 'user_sentiment']`

- [ ] **Step 4: Confirm missing-token behavior end-to-end (no crash, structured error)**

Run:
```bash
env -u NOTION_TOKEN .venv/bin/python -c "from gaa.notion import tools; print(tools.run_tool('build_updates', {}))"
```
Expected: `{'status': 'error', 'error': 'notion token not configured'}`

- [ ] **Step 5: Commit (if any incidental fixes were needed)**

```bash
git add -A && git commit -m "test(notion): full-suite green + import/launch sanity" || echo "nothing to commit"
```

---

## Task 8: Live verification against the real workspace (manual, gated)

> Credentials live in `/tmp/notion-test.env` (NOT committed). The builds source is the
> discovered `abee2267…` LiveOps calendar (the user's original `32b0e4e2…` is not shared).

**Files:** none (verification task; the orchestrator runs this — do NOT commit creds)

- [ ] **Step 1: Live smoke against the real data sources**

Run:
```bash
set -a && . /tmp/notion-test.env && set +a
export NOTION_BUILDS_DS=abee2267-021c-4a98-b91b-95d71e2a0cee
export NOTION_SENTIMENT_DS=3590e4e2-3942-8032-8e8e-000bbb4da32a
.venv/bin/python - <<'PY'
from gaa.notion import tools
print("search:", tools.run_tool("notion_search", {"query": "sentiment", "limit": 3}))
print("build_updates:", tools.run_tool("build_updates", {"limit": 3}))
print("user_sentiment:", tools.run_tool("user_sentiment", {"limit": 3}))
PY
```
Expected: all `status: success`; `build_updates` items have `title` (event names) + `Go-live Date`; `user_sentiment` items have `source` (report titles like "HGF Discord Sentiment Report …") + `date` from created_time.

- [ ] **Step 2: Live notion_fetch on a real sentiment report (body text)**

Run:
```bash
set -a && . /tmp/notion-test.env && set +a
.venv/bin/python - <<'PY'
from gaa.notion import tools
res = tools.run_tool("user_sentiment", {"limit": 1})
item = res["items"][0]
print("fetching:", item["url"])
print(tools.run_tool("notion_fetch", {"id": item["url"]}))
PY
```
Expected: `kind: page`, non-empty `text` (the report body).

---

## Task 9: Operator runbook + live-spike doc

**Files:**
- Create: `docs/notion-connect.md`
- Create: `docs/spikes/notion-api-shapes.md`

- [ ] **Step 1: Write the connect runbook**

Create `docs/notion-connect.md`:

```markdown
# Connecting Notion to the GAA agent

The `gaa.notion` MCP server ships in the image but is **inert until connected**.
Connect it once from an **admin** chat session (no redeploy needed). It uses Notion's
data-source API (`Notion-Version: 2025-09-03`).

## Prerequisites
1. In the target Notion workspace, create an **internal integration** and copy its token
   (starts with `ntn_`).
2. **Share** the relevant pages/data sources with the integration (each → `•••` →
   Connections → add your integration). The integration only sees what you share.
3. Note the **data-source IDs** for your Builds and Sentiment data sources (open the
   data source in Notion → ••• → Copy link → the 32-hex id; or use `notion_search`
   with `type=data_source`).

## Connect (admin chat)
    secret_set notion_token <your-notion-token>
    # optional — point the focused tools at specific data sources:
    secret_set notion_builds_ds <builds-data-source-id>
    secret_set notion_sentiment_ds <sentiment-data-source-id>

    mcp_add name=notion command=python3 args=["-m","gaa.notion.server"] \
      env={"NOTION_TOKEN":"notion_token","NOTION_BUILDS_DS":"notion_builds_ds","NOTION_SENTIMENT_DS":"notion_sentiment_ds"}

A supervised reload re-renders the config, wires the `notion` server, injects the
secrets, and auto-allows `notion__*` in non-admin mode.

## Tools
- `notion__build_updates(since?, until?, query?, limit?)`
- `notion__user_sentiment(since?, until?, query?, limit?)`
- `notion__notion_search(query, type?, limit?)`  — type is `page` or `data_source`
- `notion__notion_fetch(id)`  — id or URL of a page or data source

If no Builds/Sentiment data source is configured, the focused tools fall back to
workspace keyword search. Sentiment report detail lives in the page body — use
`notion_fetch` on an item's url for the full text.

## Disconnect / rotate
    mcp_remove notion
    secret_set notion_token <new-token>     # rotate
```

- [ ] **Step 2: Write the live-spike doc**

Create `docs/spikes/notion-api-shapes.md`:

```markdown
# Spike: Notion API shapes (live recon, 2026-06-16)

Confirmed against the real workspace (integration "01 [HGF] - Discord Sentiments").
Needs a real integration token; do **not** commit it.

## Findings
- Workspace uses the **data-source model**; use `Notion-Version: 2025-09-03`.
- Schema: `GET /v1/data_sources/{id}` (→ `name`, `properties`).
- Rows: `POST /v1/data_sources/{id}/query` (`sorts`/`filter`/`page_size`).
- Search: `POST /v1/search`, `filter.value` ∈ {`page`, `data_source`}.
- Pages/blocks: `GET /v1/pages/{id}`, `GET /v1/blocks/{id}/children` (unchanged).
- Old `2022-06-28` `/databases/{id}/query` → 404 for these IDs.

## Visible data sources
| Role | ID | Name | title / date / text |
|---|---|---|---|
| Builds | `abee2267-021c-4a98-b91b-95d71e2a0cee` | 04_LiveOps Calendar Content | Event Name / Go-live Date / Brief |
| Sentiment | `3590e4e2-3942-8032-8e8e-000bbb4da32a` | 10_Discord Sentiment | Report / (none→created_time) / note |

(The originally-provided builds ID `32b0e4e2…` is not shared with the integration.)

## Re-run
    set -a && . /tmp/notion-test.env && set +a
    export NOTION_BUILDS_DS=abee2267-021c-4a98-b91b-95d71e2a0cee
    .venv/bin/python - <<'PY'
    from gaa.notion import tools
    print(tools.run_tool("build_updates", {"limit": 3}))
    print(tools.run_tool("user_sentiment", {"limit": 3}))
    PY
```

- [ ] **Step 3: Commit**

```bash
git add docs/notion-connect.md docs/spikes/notion-api-shapes.md
git commit -m "docs(notion): operator connect runbook + live-recon spike notes"
```

---

## Self-Review

**Spec coverage:**
- Module `gaa.notion` (client/tools/server), decoupled from `gaa.core` → Tasks 1–6. ✅
- 4 read-only tools with exact arg shapes → `_SPECS` (Task 3) + bodies (Tasks 4–5). ✅
- **Data-source model (v2025-09-03)**, `get_data_source`/`query_data_source`, search
  `page`/`data_source`, `notion_fetch` page→data-source fallback → Tasks 1,2,4,5. ✅
- Flexible structured-vs-search resolution + best-effort property detection (validated
  against real `04_LiveOps`/`10_Discord Sentiment` schemas) → Task 5. ✅
- Sentiment date falls back to `created_time` when no date prop; `_plain` covers
  select/status/multi_select/created_time/unique_id/checkbox → Tasks 3,5. ✅
- Auth via `NOTION_TOKEN` + missing-token guard → Task 3; integration scoping is a
  Notion-side prereq → Task 9 runbook. ✅
- Errors never crash the loop; `NotionError`→structured result incl. `http_status` /
  `retry_after` → Tasks 1 + 3. ✅
- id-or-URL normalization, result truncation/caps (`_MAX_TEXT`, `_MAX_SNIPPET`, `limit`)
  → Tasks 3–5. ✅
- TDD with `httpx.MockTransport`, no live calls in CI → all test tasks; **live
  verification against the real workspace** → Task 8. ✅
- Runtime-register connect recipe (`secret_set` + `mcp_add`, data-source env names); no
  `render_config`/`pyproject`/frontend change → Task 9 runbook; confirmed by Task 7. ✅
- Read-only (no vStorage mutation path) → no snapshot call anywhere. ✅
- SOUL.md enrichment nudge + write tools explicitly **out of scope** → not in any task. ✅

**Placeholder scan:** No "TBD/TODO"; the Task-3 tool-body stubs are intentional and
replaced with full code in Tasks 4–5 (each shown in full).

**Type/name consistency:** `NotionClient`/`NotionError`; methods
`search`/`get_data_source`/`query_data_source`/`get_page`/`get_block_children`; helpers
`_client_factory`, `_normalize_id`, `_rich`, `_plain`, `_object_title`, `_blocks_to_text`,
`_row_summary`, `_focused`, `_from_data_source`, `_from_search`, `_in_range`, `_find_prop`,
`_find_named`, `_longest_rich_text`; env `NOTION_TOKEN`/`NOTION_BUILDS_DS`/
`NOTION_SENTIMENT_DS`; `_DS_ENV`. Used identically across tasks and the `conftest.py`
`mock_tools` seam patches the exact `_client_factory`. Tool names match between `_SPECS`,
`run_tool`, and `test_server`.
