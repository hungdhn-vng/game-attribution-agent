# App Store Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agent resolve a game name or genre to a Sensor Tower `app_id` via a server-side `appstore_search` tool over the public iTunes Search API, killing the `need_app_id` friction.

**Architecture:** A new `gaa/appstore/search.py` queries the public iTunes Search API (free, no-auth, runtime-reachable) and maps results to `{app_id (=App Store trackId = ST iOS app_id), name, publisher, genre, platform}`. A new `appstore_search` tool in the gaa MCP server runs it server-side (no browser/OAuth/relay — unlike the `st_*` data tools). Discovered ids feed the existing `st_*` tools.

**Tech Stack:** Python 3.11, `httpx`, `jsonschema`, pytest (`uv run pytest`; bare `python` not on PATH).

> **Environment:** branch `feat/gaa-on-openclaw`. A parallel session commits unrelated `gaa.notion` files — only touch the files each task lists; never `git add -A`; leave `uv.lock`.

---

## File Structure
- **New:** `src/gaa/appstore/__init__.py` (empty), `src/gaa/appstore/search.py` — iTunes Search client + field mapping.
- **Modified:** `src/gaa/mcp/tools.py` — add the `appstore_search` spec + a server-side router/handler.
- **Modified:** `openclaw/AGENTS.md` — playbook: resolve names/genres via `appstore_search` → use the id with `st_*`.
- **Tests:** `tests/appstore/__init__.py` (empty), `tests/appstore/test_search.py`; extend `tests/mcp/test_run_tool.py`, `tests/mcp/test_tool_specs.py`.

---

## Task 1: `gaa/appstore/search.py` — iTunes Search client

**Files:**
- Create: `src/gaa/appstore/__init__.py` (empty), `src/gaa/appstore/search.py`
- Test: `tests/appstore/__init__.py` (empty), `tests/appstore/test_search.py`

- [ ] **Step 1: Write the failing test** `tests/appstore/test_search.py`:
```python
import httpx
import pytest
from gaa.appstore import search

_PAYLOAD = {"resultCount": 2, "results": [
    {"trackId": 1480616990, "trackName": "League of Legends: Wild Rift",
     "sellerName": "Riot Games", "primaryGenreName": "Games",
     "trackViewUrl": "https://apps.apple.com/app/id1480616990"},
    {"trackName": "No Track Id App"},  # missing trackId → must be skipped
]}

def _mount(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.Client
    monkeypatch.setattr(search.httpx, "Client", lambda *a, **k: real(*a, transport=transport, **k))

def test_maps_fields_and_query(monkeypatch):
    captured = {}
    def handler(req):
        captured["url"] = str(req.url)
        return httpx.Response(200, json=_PAYLOAD)
    _mount(monkeypatch, handler)
    apps = search.search_apps("MOBA", country="VN", limit=3)
    assert apps == [{
        "app_id": 1480616990, "name": "League of Legends: Wild Rift",
        "publisher": "Riot Games", "genre": "Games", "platform": "ios",
        "url": "https://apps.apple.com/app/id1480616990",
    }]  # the entry without trackId is dropped
    u = captured["url"]
    assert "term=MOBA" in u and "country=VN" in u and "limit=3" in u and "entity=software" in u

def test_empty_results(monkeypatch):
    _mount(monkeypatch, lambda req: httpx.Response(200, json={"resultCount": 0, "results": []}))
    assert search.search_apps("zzznomatch") == []

def test_non_200_raises(monkeypatch):
    _mount(monkeypatch, lambda req: httpx.Response(503, text="down"))
    with pytest.raises(httpx.HTTPError):
        search.search_apps("x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/appstore/test_search.py -v`
Expected: FAIL (`ModuleNotFoundError: gaa.appstore`).

- [ ] **Step 3: Write minimal implementation** `src/gaa/appstore/search.py`:
```python
"""Public App Store (iTunes Search API) discovery — name/genre → candidate apps + their App Store
trackId (== Sensor Tower iOS app_id). Server-side: the runtime can reach Apple directly (no auth,
no origin allowlist), so this never needs the browser-proxy used by the st_* data tools."""
from __future__ import annotations

import httpx

_URL = "https://itunes.apple.com/search"
_TIMEOUT = 12.0


def search_apps(query: str, *, country: str = "US", limit: int = 8) -> list[dict]:
    """Return candidate apps for a name/genre term. `app_id` is the iOS App Store trackId,
    which is the Sensor Tower iOS app_id. Raises httpx.HTTPError on network/non-200."""
    params = {"term": query, "entity": "software", "country": country, "limit": limit}
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(_URL, params=params)
        r.raise_for_status()
        data = r.json()
    apps = []
    for res in data.get("results", []):
        tid = res.get("trackId")
        if tid is None:
            continue
        apps.append({
            "app_id": tid,
            "name": res.get("trackName"),
            "publisher": res.get("sellerName"),
            "genre": res.get("primaryGenreName"),
            "platform": "ios",
            "url": res.get("trackViewUrl"),
        })
    return apps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/appstore/test_search.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/appstore/__init__.py src/gaa/appstore/search.py tests/appstore/__init__.py tests/appstore/test_search.py
git commit -m "feat(appstore): iTunes Search client (name/genre -> app candidates + app_id)"
```

---

## Task 2: `appstore_search` tool in the gaa MCP server

**Files:**
- Modify: `src/gaa/mcp/tools.py`
- Test: `tests/mcp/test_run_tool.py`, `tests/mcp/test_tool_specs.py`

**Context:** `tools.py` has `_SPECS` (name → (desc, schema)), `tool_specs(is_admin)`, and `run_tool(ctx, name, arguments, *, is_admin)`. The `st_*` tools are routed in `run_tool` after `jsonschema.validate(...)` and before `actions.dispatch(...)`. Add `appstore_search` the same way — it's server-side (the handler doesn't touch `ctx`, doesn't use guard/cache/relay) and non-admin (NOT added to `actions.ADMIN_ACTIONS`).

- [ ] **Step 1: Write the failing tests.**

In `tests/mcp/test_tool_specs.py` add:
```python
def test_specs_include_appstore_search():
    from gaa.mcp import tools as _t
    assert "appstore_search" in {t["name"] for t in _t.tool_specs(is_admin=False)}
```
In `tests/mcp/test_run_tool.py` add (reuse the existing `mcp_tools` import + `FakeCtx`):
```python
def test_appstore_search_returns_apps(monkeypatch):
    monkeypatch.setattr(mcp_tools, "_appstore_search",
                        lambda query, country, limit: [{"app_id": 1, "name": "G", "platform": "ios"}])
    out = mcp_tools.run_tool(FakeCtx(), "appstore_search", {"query": "MOBA"}, is_admin=False)
    assert out == {"apps": [{"app_id": 1, "name": "G", "platform": "ios"}]}

def test_appstore_search_passes_args(monkeypatch):
    seen = {}
    def fake(query, country, limit):
        seen.update(query=query, country=country, limit=limit)
        return []
    monkeypatch.setattr(mcp_tools, "_appstore_search", fake)
    mcp_tools.run_tool(FakeCtx(), "appstore_search", {"query": "RPG", "country": "VN", "limit": 3}, is_admin=False)
    assert seen == {"query": "RPG", "country": "VN", "limit": 3}

def test_appstore_search_error_is_structured(monkeypatch):
    def boom(query, country, limit):
        raise RuntimeError("itunes down")
    monkeypatch.setattr(mcp_tools, "_appstore_search", boom)
    out = mcp_tools.run_tool(FakeCtx(), "appstore_search", {"query": "x"}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "appstore_unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/mcp/test_run_tool.py tests/mcp/test_tool_specs.py -k appstore -v`
Expected: FAIL (`unknown tool: 'appstore_search'` / name missing).

- [ ] **Step 3: Implement** in `src/gaa/mcp/tools.py`.

Add the import near the other sensortower imports:
```python
from gaa.appstore import search as _appstore
```
Add a module-level indirection (so tests monkeypatch without httpx):
```python
def _appstore_search(query: str, country: str, limit: int) -> list[dict]:
    return _appstore.search_apps(query, country=country, limit=limit)
```
Add to `_SPECS`:
```python
    "appstore_search": ("Find apps by name or genre on the public App Store. Returns candidates each with an `app_id` (= the Sensor Tower iOS app id), name, publisher, genre. Use this to turn a game name or genre into an app_id, then pass that id to the st_* tools (and st_set_app_id to remember it).",
                        {"type": "object",
                         "properties": {"query": _STR, "country": _STR, "limit": {"type": "integer"}},
                         "required": ["query"]}),
```
Add the router in `run_tool`, right after the `st_*` router block (after `jsonschema.validate`, before `actions.dispatch`):
```python
    if name == "appstore_search":
        a = arguments or {}
        try:
            apps = _appstore_search(a["query"], a.get("country", "US"), a.get("limit", 8))
        except Exception as exc:
            _log.exception("appstore_search failed")
            return {"status": "error", "error": "appstore_unavailable", "detail": str(exc)}
        return {"apps": apps}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/ -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/mcp/tools.py tests/mcp/test_run_tool.py tests/mcp/test_tool_specs.py
git commit -m "feat(appstore): appstore_search tool (server-side name/genre -> app_id)"
```

---

## Task 3: Agent playbook (AGENTS.md)

**Files:** Modify `openclaw/AGENTS.md` (the Sensor Tower section).

- [ ] **Step 1: Add the discovery step** — insert into the `## Sensor Tower` section, right after the "IMPORTANT — these tools are ID-based…" bullet:
```markdown
- To get an app_id from a game NAME or a GENRE, call `appstore_search(query)` (e.g.
  `appstore_search("Mobile Legends")` or `appstore_search("MOBA")`). It returns candidate apps
  each with an `app_id`. Pick the right one (confirm with the user if ambiguous), then pass that
  `app_id` to the st_* tools and call `st_set_app_id(label, app_id)` to remember it. Do this
  instead of asking the user to paste an id. Discovered ids are iOS App Store ids — use them with
  `st_app_performance`/`st_download_channel`/`st_app_store`/`st_search_optimization` (not the
  unified tool, which needs a different id).
```

- [ ] **Step 2: Commit**
```bash
git add openclaw/AGENTS.md
git commit -m "feat(appstore): playbook — resolve names/genres via appstore_search"
```

---

## Task 4: Full suite + Phase-0 live verify + deploy

- [ ] **Step 1: Run the whole Python suite.**

Run: `uv run pytest -q`
Expected: all green (existing + the new appstore tests).

- [ ] **Step 2: Phase-0 live verify (manual, after deploy or locally with network).**

A real iTunes call returns mapped candidates:
```bash
uv run python -c "from gaa.appstore import search; import json; print(json.dumps(search.search_apps('MOBA', limit=3), indent=2))"
```
Expected: a list of apps with numeric `app_id`s + names (e.g. League of Legends: Wild Rift `1480616990`). **Then verify the bridge**: in the live chat (Sensor Tower connected), `appstore_search` a game → take its `app_id` → `st_app_performance(app_ids=[<id>])` → expect real ST data (not "Failed to find any apps"). This confirms `trackId` == ST iOS `app_id`.

- [ ] **Step 3: Deploy (server-side only — no frontend/env changes).**

Build + push the combined image and rolling-update `gaa-custom-agent` (per `/agentbase-deploy`; same flavor `runtime-s2-general-2x4`, env, PUBLIC). Then apply the new `openclaw/AGENTS.md` to the live instance via admin `self_edit` (the persisted workspace copy overrides the seed — see [[custom-agent-deploy-gotchas]]): the admin agent runs `cp /opt/gaa/openclaw/AGENTS.md "$OPENCLAW_WORKSPACE/AGENTS.md"` + a `persist.snapshot`. (The new image carries the new playbook, so the cp-from-image approach works this time.)

---

## Self-Review notes

- **Spec coverage:** `search.py` iTunes client + field mapping (Task 1); `appstore_search` server-side tool + error contract `appstore_unavailable` + empty `{apps:[]}` (Task 2); iOS-scope + id-bridge guidance in the playbook (Task 3); full suite + the `trackId`==ST-id Phase-0 verify + server-side-only deploy (Task 4). Deferred items (Android/unified, RSS top-charts, caching) are out of scope per the spec.
- **No placeholders:** every step has concrete code/commands; `search_apps(query,*,country,limit)` and the `_appstore_search(query,country,limit)` indirection signatures match between Task 1 and Task 2.
- **Type consistency:** the result dict shape `{app_id,name,publisher,genre,platform,url}` is identical in `search.py` and the tests; the tool returns `{apps:[...]}` / `{status:error,error:"appstore_unavailable"}` consistently.
