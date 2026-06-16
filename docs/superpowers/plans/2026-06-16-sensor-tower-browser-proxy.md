# Sensor Tower Browser-Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the GAA agent pull live, multi-game Sensor Tower market data despite the runtime being 403-blocked, by building+budget-guarding queries in the runtime and executing them through the user's VNG-network browser, with a global query-keyed cache.

**Architecture:** Runtime (Python) = brains: guarded `st_*` tools → resolve app-IDs → fill defaults/cap budget → check a vStorage-persisted cache → on miss, relay via a sidecar. The front-door surfaces the pending request as an `st_request` SSE event and accepts the browser's result on a bearer-gated `/sensor-tower/fulfill`. Browser (TS) = muscle: holds the O365 token (client-side OAuth), runs the ST MCP call, posts the result back.

**Tech Stack:** Python 3.11 (`uv run pytest`; bare `python` is NOT on PATH), FastAPI, sqlite, `httpx`; Next.js (App Router, TS) frontend with `vitest`.

> **Environment:** branch `feat/gaa-on-openclaw`. A parallel session commits unrelated `gaa.notion` files — only touch the files each task lists; never `git add -A`; leave `uv.lock`. Tests: `uv run pytest …` (Python), `cd frontend && pnpm vitest run …` and `pnpm exec tsc --noEmit` (frontend).

---

## Shared relay contract (both sides depend on these exact shapes — do not drift)

- **Built ST request** (runtime → relay → browser): `{"req_id": str, "st_tool": str, "params": {…}}` where `st_tool` is the real ST tool name (e.g. `app_performance_api_v2_app_performance_get`) and `params` is the fully-defaulted ST argument object.
- **Pending sidecar** `GAA_ST_REQUEST` (default `$GAA_CACHE_DIR/sensortower/st_request.json`): the latest built request JSON (single active request).
- **`st_request` SSE event** (front-door → browser): `{"type":"st_request","req_id":str,"st_tool":str,"params":{…}}`.
- **Fulfillment** (browser → frontend → agent `POST /sensor-tower/fulfill`): `{"req_id":str,"result":{…}}` **or** `{"req_id":str,"error":{"kind":str,"detail":str}}` where `kind ∈ {"not_connected","upstream_error"}`.
- **Result sidecar** `GAA_ST_RESULT` (default `$GAA_CACHE_DIR/sensortower/st_result.json`): `{"req_id":str,"result":{…}}` or `{"req_id":str,"error":{…}}`.
- **Tool result back to the LLM** (one of): `{"data":…,"cached":bool,"scope_trimmed":[…]}` | `{"status":"error","error":"need_app_id","labels":[…]}` | `{"status":"error","error":"not_connected"}` | `{"status":"error","error":"upstream_error","detail":…}` | `{"status":"error","error":"fulfill_timeout"}`.

---

## File Structure

**New (Python):**
- `src/gaa/sensortower/appids.py` — per-profile app-ID map (own table in the profiles DB).
- `src/gaa/sensortower/cache.py` — global query-keyed result cache (vStorage-snapshotted).
- `src/gaa/sensortower/guard.py` — per-tool defaults, budget estimate/cap/trim, app-ID resolution, build request.
- `src/gaa/sensortower/relay.py` — pending-sidecar write + result poll + timeout + `req_id` correlation.

**Modified (Python):**
- `src/gaa/mcp/tools.py` — add `st_*` + `st_set_app_id` tools; route guard→cache→relay; retire the old direct `sensor_tower_call`/`sensor_tower_list_tools` from the agent surface.
- `src/gaa/persist.py` — snapshot the cache + (already) profiles DB.
- `src/gaa/server/openclaw_client.py` — add an `st_request` poller (mirror `_poll_progress`).
- `src/gaa/server/app.py` — `POST /sensor-tower/fulfill`.
- `src/gaa/server/openclaw_config.py` — pass `GAA_ST_REQUEST`/`GAA_ST_RESULT` to the gaa MCP server env.
- `openclaw/AGENTS.md` — connect+ST playbook.

**New (frontend, TS):**
- `frontend/lib/gaa/st-oauth.ts` — PKCE helpers + token storage.
- `frontend/lib/gaa/st-client.ts` — execute a built ST request over MCP streamable-HTTP.
- `frontend/app/sensor-tower/connected/page.tsx` — OAuth callback page (client-side token exchange).
- `frontend/app/api/sensor-tower/fulfill/route.ts` — relay the result to the agent.
- `frontend/components/gaa/sensor-tower-connect.tsx` — Connect button + status.

**Modified (frontend):**
- `frontend/components/gaa/use-gaa-chat.ts` — handle `st_request` events.
- `frontend/lib/gaa/sse.ts` — add `st_request` to the `GaaEvent` union.

**Tests:** `tests/sensortower/test_appids.py`, `test_cache.py`, `test_guard.py`, `test_relay.py`; extend `tests/mcp/test_run_tool.py`, `tests/mcp/test_tool_specs.py`, `tests/server/test_app_routes.py`, `tests/test_persist.py`, `tests/server/` (poller); frontend `frontend/tests/gaa/st-oauth.test.ts`, `st-client.test.ts`.

---

# PHASE A — Runtime core (Python)

## Task A1: `appids.py` — per-profile app-ID store

**Files:** Create `src/gaa/sensortower/__init__.py` *(if absent — it already exists from the prior build; skip if present)*, `src/gaa/sensortower/appids.py`. Test: `tests/sensortower/test_appids.py`.

App-ID map lives in its own table in the **profiles** sqlite (already snapshotted via arcname `profiles.sqlite`), keyed by profile name — keeps the core `GameProfile` schema untouched.

- [ ] **Step 1: failing test** `tests/sensortower/test_appids.py`:
```python
from gaa.sensortower import appids

def test_set_get_resolve(tmp_path):
    db = str(tmp_path / "p.sqlite")
    appids.set_app_id(db, "mygame", "self", 12345, "app_id")
    appids.set_app_id(db, "mygame", "competitor:clash", 678, "product_id")
    assert appids.get_app_ids(db, "mygame") == {
        "self": {"id": 12345, "id_type": "app_id"},
        "competitor:clash": {"id": 678, "id_type": "product_id"},
    }
    assert appids.resolve(db, "mygame", "self") == {"id": 12345, "id_type": "app_id"}
    assert appids.resolve(db, "mygame", "missing") is None
    assert appids.get_app_ids(db, "other") == {}

def test_set_overwrites(tmp_path):
    db = str(tmp_path / "p.sqlite")
    appids.set_app_id(db, "g", "self", 1, "app_id")
    appids.set_app_id(db, "g", "self", 2, "app_id")
    assert appids.resolve(db, "g", "self")["id"] == 2
```
- [ ] **Step 2: run, expect FAIL** — `uv run pytest tests/sensortower/test_appids.py -v`
- [ ] **Step 3: implement** `src/gaa/sensortower/appids.py`:
```python
"""Per-profile Sensor Tower app-ID map, stored in its own table inside the profiles
sqlite (snapshotted via the profiles.sqlite arcname). Keeps GameProfile untouched."""
from __future__ import annotations

import sqlite3


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.execute(
        "CREATE TABLE IF NOT EXISTS st_app_ids "
        "(profile TEXT, label TEXT, id TEXT NOT NULL, id_type TEXT NOT NULL, "
        " PRIMARY KEY (profile, label))"
    )
    return c


def set_app_id(db_path: str, profile: str, label: str, id, id_type: str = "app_id") -> None:
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO st_app_ids(profile,label,id,id_type) VALUES(?,?,?,?) "
            "ON CONFLICT(profile,label) DO UPDATE SET id=excluded.id, id_type=excluded.id_type",
            (profile, label, str(id), id_type),
        )


def _coerce(id_str: str):
    try:
        return int(id_str)
    except (TypeError, ValueError):
        return id_str


def get_app_ids(db_path: str, profile: str) -> dict:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT label,id,id_type FROM st_app_ids WHERE profile=?", (profile,)
        ).fetchall()
    return {lbl: {"id": _coerce(i), "id_type": t} for lbl, i, t in rows}


def resolve(db_path: str, profile: str, label: str):
    return get_app_ids(db_path, profile).get(label)
```
- [ ] **Step 4: run, expect PASS** — `uv run pytest tests/sensortower/test_appids.py -v`
- [ ] **Step 5: commit**
```bash
git add src/gaa/sensortower/appids.py tests/sensortower/test_appids.py
git commit -m "feat(sensortower): per-profile app-ID store"
```

---

## Task A2: `cache.py` — global query-keyed result cache

**Files:** Create `src/gaa/sensortower/cache.py`. Test: `tests/sensortower/test_cache.py`.

Single JSON file `$GAA_CACHE_DIR/sensortower/st_cache.json`: `{key: {data, end_date, ts, last}}`. TTL 7d, 24h if `end_date` within 3 days of now. LRU by `last`, capped at `_MAX_ENTRIES`. `now` injected for tests.

- [ ] **Step 1: failing test** `tests/sensortower/test_cache.py`:
```python
from gaa.sensortower import cache

def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "c"))

def test_key_normalizes_equivalent_queries():
    a = {"st_tool": "x", "params": {"app_id": [2, 1], "countries": ["US", "VN"], "bundles": ["b"]}}
    b = {"st_tool": "x", "params": {"bundles": ["b"], "countries": ["VN", "US"], "app_id": [1, 2]}}
    assert cache.make_key(a) == cache.make_key(b)

def test_put_get_hit(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    cache.put("k", {"v": 1}, end_date="2024-01-01", now=1000.0)
    assert cache.get("k", now=1000.0) == {"v": 1}

def test_miss_returns_none(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert cache.get("nope", now=1000.0) is None

def test_ttl_historical_7d(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    cache.put("k", {"v": 1}, end_date="2020-01-01", now=0.0)
    assert cache.get("k", now=6 * 86400) == {"v": 1}      # within 7d
    assert cache.get("k", now=8 * 86400) is None          # expired

def test_ttl_recent_24h(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    # end_date == "now": within the recent 3-day window → 24h TTL
    cache.put("k", {"v": 1}, end_date="1970-01-02", now=86400.0)  # now=day1, end_date=day1
    assert cache.get("k", now=86400.0 + 23 * 3600) == {"v": 1}
    assert cache.get("k", now=86400.0 + 25 * 3600) is None

def test_lru_eviction(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    monkeypatch.setattr(cache, "_MAX_ENTRIES", 2)
    cache.put("a", {}, end_date="2020-01-01", now=1.0)
    cache.put("b", {}, end_date="2020-01-01", now=2.0)
    cache.get("a", now=3.0)                 # touch a → b is now LRU
    cache.put("c", {}, end_date="2020-01-01", now=4.0)  # evicts b
    assert cache.get("b", now=5.0) is None
    assert cache.get("a", now=5.0) == {}
```
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** `src/gaa/sensortower/cache.py`:
```python
"""Global, query-keyed Sensor Tower result cache. One JSON file under GAA_CACHE_DIR,
added to persist._durable_items → snapshotted to vStorage (cross-session/restart).
A hit short-circuits the browser relay (no data points spent)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

_MAX_ENTRIES = 500
_TTL_DEFAULT = 7 * 86400
_TTL_RECENT = 86400
_RECENT_WINDOW_DAYS = 3


def store_path() -> str:
    return str(Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower" / "st_cache.json")


def _dir() -> Path:
    d = Path(store_path()).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_key(built: dict) -> str:
    """Stable hash of the normalized built request (sorted lists, sorted keys)."""
    def norm(v):
        if isinstance(v, list):
            return sorted(norm(x) for x in v)
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v)}
        return v
    payload = json.dumps({"st_tool": built["st_tool"], "params": norm(built.get("params", {}))},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _read() -> dict:
    try:
        with open(store_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    _dir()
    path = store_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)


def _ttl_for(end_date: str, now: float) -> int:
    try:
        ed = date.fromisoformat(end_date)
        now_d = date.fromtimestamp(now)
        if (now_d - ed).days <= _RECENT_WINDOW_DAYS:
            return _TTL_RECENT
    except (TypeError, ValueError):
        pass
    return _TTL_DEFAULT


def get(key: str, *, now: float):
    d = _read()
    e = d.get(key)
    if not e:
        return None
    if now - e["ts"] >= _ttl_for(e.get("end_date", ""), now):
        return None
    e["last"] = now          # LRU touch
    _write(d)
    return e["data"]


def put(key: str, data, *, end_date: str, now: float) -> None:
    d = _read()
    d[key] = {"data": data, "end_date": end_date, "ts": now, "last": now}
    if len(d) > _MAX_ENTRIES:
        for k in sorted(d, key=lambda k: d[k]["last"])[: len(d) - _MAX_ENTRIES]:
            del d[k]
    _write(d)
```
- [ ] **Step 4: run, expect PASS**
- [ ] **Step 5: commit**
```bash
git add src/gaa/sensortower/cache.py tests/sensortower/test_cache.py
git commit -m "feat(sensortower): global query-keyed result cache (TTL + LRU)"
```

---

## Task A3: snapshot the cache to vStorage

**Files:** Modify `src/gaa/persist.py` (`_durable_items`). Test: extend `tests/test_persist.py`.

- [ ] **Step 1: failing test** add to `tests/test_persist.py`:
```python
def test_durable_items_include_sensortower_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    from gaa.cli.wiring import build_context
    from gaa.core.llm.client import FakeLLM
    from gaa import persist
    from gaa.sensortower import cache
    ctx = build_context(llm=FakeLLM({}))
    cache.put("k", {"v": 1}, end_date="2020-01-01", now=1.0)
    arcnames = {arc for arc, _p, _d in persist._durable_items(ctx)}
    assert "sensortower_cache.json" in arcnames
```
- [ ] **Step 2: run, expect FAIL** — `uv run pytest tests/test_persist.py::test_durable_items_include_sensortower_cache -v`
- [ ] **Step 3: implement** — in `_durable_items`, add the import alongside the existing sensortower import and append the entry:
```python
    from gaa.sensortower import store as st_store, cache as st_cache
    # … existing entries …
        ("sensortower_state.json", Path(st_store.store_path()), False),
        ("sensortower_cache.json", Path(st_cache.store_path()), False),
    ]
```
(Keep the existing `sensortower_state.json` line; just add the cache line after it and extend the import.)
- [ ] **Step 4: run, expect PASS** — `uv run pytest tests/test_persist.py -v`
- [ ] **Step 5: commit**
```bash
git add src/gaa/persist.py tests/test_persist.py
git commit -m "feat(sensortower): snapshot result cache to vStorage"
```

---

## Task A4: `guard.py` — defaults, budget cap, app-ID resolution, build

**Files:** Create `src/gaa/sensortower/guard.py`. Test: `tests/sensortower/test_guard.py`.

Per-tool config maps our tool key → ST tool name + id param + default devices/granularity/bundle. `build()` resolves apps (raw `app_ids` + `labels` via a resolver callback), fills defaults, estimates `apps × countries × devices × date_count × bundles`, trims (countries → shorten range → coarsen granularity → drop apps) until ≤ `_CAP`, returns `{"built": {...}}` or `{"status":"error","error":"need_app_id","labels":[…]}`.

- [ ] **Step 1: failing test** `tests/sensortower/test_guard.py`:
```python
from gaa.sensortower import guard

def _resolver(label):
    return {"self": {"id": 111, "id_type": "app_id"}}.get(label)

def test_need_app_id_when_unresolved():
    out = guard.build("st_app_performance", {"labels": ["self", "ghost"],
                      "start_date": "2024-01-01", "end_date": "2024-03-01"},
                      resolver=_resolver, today="2024-06-01")
    assert out == {"status": "error", "error": "need_app_id", "labels": ["ghost"]}

def test_build_fills_defaults_and_maps_ids():
    out = guard.build("st_app_performance", {"app_ids": [111],
                      "start_date": "2024-01-01", "end_date": "2024-03-01"},
                      resolver=_resolver, today="2024-06-01")
    b = out["built"]
    assert b["st_tool"] == "app_performance_api_v2_app_performance_get"
    p = b["params"]
    assert p["app_id"] == [111]
    assert p["devices"] == ["ios-all", "android-all"]
    assert p["granularity"] == "monthly"
    assert p["bundles"] == ["download_revenue"]
    assert p["countries"] == ["US"]

def test_labels_resolve_and_merge():
    out = guard.build("st_app_performance", {"labels": ["self"], "app_ids": [222],
                      "start_date": "2024-01-01", "end_date": "2024-02-01"},
                      resolver=_resolver, today="2024-06-01")
    assert sorted(out["built"]["params"]["app_id"]) == [111, 222]

def test_default_date_range_90d_when_unspecified():
    out = guard.build("st_app_performance", {"app_ids": [111]},
                      resolver=_resolver, today="2024-06-01")
    p = out["built"]["params"]
    assert p["end_date"] == "2024-06-01" and p["start_date"] == "2024-03-03"  # 90 days back

def test_budget_trim_countries(monkeypatch):
    monkeypatch.setattr(guard, "_CAP", 10)
    out = guard.build("st_app_store", {"app_ids": [111], "countries": ["US","VN","JP","KR","GB"],
                      "start_date": "2024-01-01", "end_date": "2024-01-05"},
                      resolver=_resolver, today="2024-06-01")
    # app_store is daily; 1 app * 5 countries * 2 devices * 5 days * 1 bundle = 50 > 10 → trim countries
    assert len(out["built"]["params"]["countries"]) < 5
    assert "countries" in (out.get("scope_trimmed") or [])

def test_apps_cap_10():
    out = guard.build("st_app_performance", {"app_ids": list(range(20)),
                      "start_date": "2024-01-01", "end_date": "2024-02-01"},
                      resolver=_resolver, today="2024-06-01")
    assert len(out["built"]["params"]["app_id"]) <= 10
```
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** `src/gaa/sensortower/guard.py`:
```python
"""Build a budget-guarded Sensor Tower request from the LLM's loose args: resolve app-IDs,
fill the heavy defaults, and estimate+cap data points (apps × countries × devices × dates ×
bundles) so a single query can't drain the shared monthly allowance."""
from __future__ import annotations

from datetime import date, timedelta

_CAP = 50_000
_MAX_APPS = 10
_MAX_COUNTRIES = 5
_DEFAULT_RANGE_DAYS = 90

# our tool key -> (ST tool name, id param, default devices, default granularity, default bundle, unified?)
_TOOLS = {
    "st_app_performance": ("app_performance_api_v2_app_performance_get", "app_id",
                           ["ios-all", "android-all"], "monthly", "download_revenue", False),
    "st_unified_app_performance": ("unified_app_performance_api_v2_unified_app_performance_g",
                                   "unified_app_id", ["all"], "monthly", "download_revenue", True),
    "st_download_channel": ("download_channel_api_v2_download_channel_get", "app_id",
                            ["ios-all", "android-all"], "monthly", "download_channel", False),
    "st_app_store": ("app_store_api_v2_app_store_get", "app_id",
                     ["ios-all", "android-all"], "daily", "ranks", False),
    "st_search_optimization": ("search_optimization_api_v2_search_optimization_get", "app_id",
                               ["ios-phone", "android-phone"], "daily", "keywords", False),
}
_GRAN_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}
_COARSER = {"daily": "weekly", "weekly": "monthly", "monthly": "quarterly"}


def _date_count(start: str, end: str, gran: str) -> int:
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except (TypeError, ValueError):
        days = 1
    return max(1, days // _GRAN_DAYS.get(gran, 30))


def _estimate(p: dict, gran: str) -> int:
    apps = max(1, len(p.get("app_id") or p.get("unified_app_id") or [1]))
    return (apps * max(1, len(p["countries"])) * max(1, len(p["devices"]))
            * _date_count(p["start_date"], p["end_date"], gran) * 1)


def build(tool_key: str, args: dict, *, resolver, today: str) -> dict:
    st_tool, id_param, dft_devices, dft_gran, dft_bundle, unified = _TOOLS[tool_key]

    # --- resolve app ids: explicit + labels ---
    ids = list(args.get("app_ids") or [])
    unresolved = []
    for label in args.get("labels") or []:
        rec = resolver(label)
        if rec:
            ids.append(rec["id"])
        else:
            unresolved.append(label)
    if unresolved:
        return {"status": "error", "error": "need_app_id", "labels": unresolved}
    ids = list(dict.fromkeys(ids))[:_MAX_APPS]  # dedup, cap

    # --- dates: default last 90d ---
    end = args.get("end_date") or today
    if args.get("start_date"):
        start = args["start_date"]
    else:
        start = (date.fromisoformat(end) - timedelta(days=_DEFAULT_RANGE_DAYS)).isoformat()

    countries = (args.get("countries") or ["US"])[:_MAX_COUNTRIES]
    trimmed = []
    if args.get("countries") and len(args["countries"]) > _MAX_COUNTRIES:
        trimmed.append("countries")

    params = {
        id_param: ids,
        "start_date": start, "end_date": end,
        "countries": countries,
        "devices": dft_devices,
        "granularity": dft_gran,
        "bundles": [dft_bundle],
        "metrics": args.get("metrics") or [],
    }
    if tool_key == "st_search_optimization" and args.get("keyword"):
        params["keyword"] = args["keyword"]

    # --- budget trim: countries → shorten range → coarsen granularity → drop apps ---
    gran = params["granularity"]
    while _estimate(params, gran) > _CAP:
        if len(params["countries"]) > 1:
            params["countries"] = params["countries"][: max(1, len(params["countries"]) // 2)]
            _note(trimmed, "countries")
        elif _date_count(params["start_date"], params["end_date"], gran) > 2:
            params["start_date"] = (date.fromisoformat(params["end_date"]) - timedelta(days=30)).isoformat()
            _note(trimmed, "date_range")
        elif gran in _COARSER:
            gran = params["granularity"] = _COARSER[gran]
            _note(trimmed, "granularity")
        elif len(params[id_param]) > 1:
            params[id_param] = params[id_param][:-1]
            _note(trimmed, "apps")
        else:
            break

    out = {"built": {"st_tool": st_tool, "params": params}}
    if trimmed:
        out["scope_trimmed"] = trimmed
    return out


def _note(lst, item):
    if item not in lst:
        lst.append(item)
```
- [ ] **Step 4: run, expect PASS** — fix any default-date arithmetic the test pins (90 days before 2024-06-01 is 2024-03-03).
- [ ] **Step 5: commit**
```bash
git add src/gaa/sensortower/guard.py tests/sensortower/test_guard.py
git commit -m "feat(sensortower): query guard (defaults, budget cap/trim, app-id resolve)"
```

---

## Task A5: `relay.py` — pending-sidecar write + result poll

**Files:** Create `src/gaa/sensortower/relay.py`. Test: `tests/sensortower/test_relay.py`.

`request(built, *, timeout, poll, now_fn)`: assign `req_id`, write the pending sidecar, poll the result sidecar until its `req_id` matches (return `result` or map `error`), else `fulfill_timeout`. Paths from `GAA_ST_REQUEST` / `GAA_ST_RESULT` (default under `GAA_CACHE_DIR/sensortower/`).

- [ ] **Step 1: failing test** `tests/sensortower/test_relay.py`:
```python
import json, threading, time
from pathlib import Path
from gaa.sensortower import relay

def _paths(tmp_path, monkeypatch):
    req = tmp_path / "st_request.json"; res = tmp_path / "st_result.json"
    monkeypatch.setenv("GAA_ST_REQUEST", str(req)); monkeypatch.setenv("GAA_ST_RESULT", str(res))
    return req, res

def test_request_returns_matching_result(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    def fake_browser():
        for _ in range(200):
            if req.exists():
                rid = json.loads(req.read_text())["req_id"]
                res.write_text(json.dumps({"req_id": rid, "result": {"v": 9}}))
                return
            time.sleep(0.01)
    t = threading.Thread(target=fake_browser); t.start()
    out = relay.request({"st_tool": "x", "params": {}}, timeout=5, poll=0.02)
    t.join()
    assert out == {"result": {"v": 9}}

def test_request_maps_error(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    def fake_browser():
        for _ in range(200):
            if req.exists():
                rid = json.loads(req.read_text())["req_id"]
                res.write_text(json.dumps({"req_id": rid, "error": {"kind": "not_connected"}}))
                return
            time.sleep(0.01)
    t = threading.Thread(target=fake_browser); t.start()
    out = relay.request({"st_tool": "x", "params": {}}, timeout=5, poll=0.02)
    t.join()
    assert out == {"error": {"kind": "not_connected"}}

def test_timeout(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    out = relay.request({"st_tool": "x", "params": {}}, timeout=0.2, poll=0.02)
    assert out == {"error": {"kind": "fulfill_timeout"}}

def test_stale_result_ignored(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    res.write_text(json.dumps({"req_id": "OLD", "result": {"stale": True}}))  # pre-existing stale
    out = relay.request({"st_tool": "x", "params": {}}, timeout=0.2, poll=0.02)
    assert out == {"error": {"kind": "fulfill_timeout"}}  # stale req_id never matches
```
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** `src/gaa/sensortower/relay.py`:
```python
"""Hand a built ST request to the browser (which can reach ST) and block for its result.
Cross-process via two sidecar files; the front-door emits the st_request SSE event from the
pending sidecar and writes the result sidecar from POST /sensor-tower/fulfill."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def _req_path() -> str:
    return os.environ.get("GAA_ST_REQUEST") or str(
        Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower" / "st_request.json")


def _res_path() -> str:
    return os.environ.get("GAA_ST_RESULT") or str(
        Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower" / "st_result.json")


def request(built: dict, *, timeout: float = 120.0, poll: float = 0.3, now_fn=time.time) -> dict:
    req_id = uuid.uuid4().hex
    rp = Path(_req_path()); rp.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(rp) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"req_id": req_id, "st_tool": built["st_tool"], "params": built["params"]}, f)
    os.replace(tmp, str(rp))

    deadline = now_fn() + timeout
    res = Path(_res_path())
    while now_fn() < deadline:
        try:
            rec = json.loads(res.read_text())
        except (OSError, ValueError):
            rec = None
        if rec and rec.get("req_id") == req_id:
            if "result" in rec:
                return {"result": rec["result"]}
            return {"error": rec.get("error") or {"kind": "upstream_error"}}
        time.sleep(poll)
    return {"error": {"kind": "fulfill_timeout"}}
```
- [ ] **Step 4: run, expect PASS**
- [ ] **Step 5: commit**
```bash
git add src/gaa/sensortower/relay.py tests/sensortower/test_relay.py
git commit -m "feat(sensortower): browser relay (pending/result sidecars, req_id correlation)"
```

---

## Task A6: wire `st_*` tools (guard → cache → relay) into the gaa MCP server

**Files:** Modify `src/gaa/mcp/tools.py`. Test: extend `tests/mcp/test_run_tool.py`, `tests/mcp/test_tool_specs.py`.

Add specs for `st_app_performance`, `st_unified_app_performance`, `st_download_channel`, `st_app_store`, `st_search_optimization`, `st_set_app_id`. The handler: resolve via guard (using a resolver bound to the active profile), `need_app_id`→return; cache.get (unless `refresh`)→hit returns `{data,cached:true}`; miss→relay.request→ map result/error; on success cache.put + return `{data,cached:false,scope_trimmed}`. **Retire** the old direct `sensor_tower_call`/`sensor_tower_list_tools` from `_SPECS` (the browser path replaces them); keep `sensor_tower_status`/`sensor_tower_connect` only if still wanted — for v1 connect is browser-UI-driven, so remove all four old `sensor_tower_*` tools to avoid 403-bound dead tools.

- [ ] **Step 1: failing tests** add to `tests/mcp/test_tool_specs.py`:
```python
def test_specs_include_st_browser_tools():
    from gaa.mcp import tools as _t
    names = {t["name"] for t in _t.tool_specs(is_admin=False)}
    assert {"st_app_performance", "st_unified_app_performance", "st_download_channel",
            "st_app_store", "st_search_optimization", "st_set_app_id"} <= names

def test_old_direct_sensor_tower_tools_removed():
    from gaa.mcp import tools as _t
    names = {t["name"] for t in _t.tool_specs(is_admin=True)}
    assert "sensor_tower_call" not in names and "sensor_tower_list_tools" not in names
```
add to `tests/mcp/test_run_tool.py`:
```python
import time as _t
from gaa.mcp import tools as mcp_tools

def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "g.sqlite"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "g.toml"))
    from gaa.cli.wiring import build_context
    from gaa.core.llm.client import FakeLLM
    return build_context(llm=FakeLLM({}))

def test_st_tool_cache_hit_skips_relay(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    called = {"relay": 0}
    monkeypatch.setattr(mcp_tools, "_st_relay", lambda built: (_ for _ in ()).throw(AssertionError("relay called")))
    # pre-resolve an app id on the active profile so guard succeeds
    monkeypatch.setattr(mcp_tools, "_st_resolver_for", lambda ctx: (lambda label: None))
    # seed cache for the exact built key
    from gaa.sensortower import guard, cache
    built = guard.build("st_app_performance", {"app_ids":[111],"start_date":"2024-01-01","end_date":"2024-02-01"},
                        resolver=lambda l: None, today="2024-06-01")["built"]
    cache.put(cache.make_key(built), {"hit": True}, end_date="2024-02-01", now=_t.time())
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"app_ids":[111],"start_date":"2024-01-01","end_date":"2024-02-01"}, is_admin=False)
    assert out["cached"] is True and out["data"] == {"hit": True}

def test_st_tool_relay_on_miss(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    monkeypatch.setattr(mcp_tools, "_st_relay", lambda built: {"result": {"fresh": 1}})
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"app_ids":[222],"start_date":"2024-01-01","end_date":"2024-02-01"}, is_admin=False)
    assert out["cached"] is False and out["data"] == {"fresh": 1}

def test_st_tool_not_connected(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    monkeypatch.setattr(mcp_tools, "_st_relay", lambda built: {"error": {"kind": "not_connected"}})
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"app_ids":[1],"start_date":"2024-01-01","end_date":"2024-02-01"}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "not_connected"

def test_st_tool_need_app_id(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"labels":["ghost"],"start_date":"2024-01-01","end_date":"2024-02-01"}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "need_app_id" and out["labels"] == ["ghost"]
```
- [ ] **Step 2: run, expect FAIL** — `uv run pytest tests/mcp/ -v`
- [ ] **Step 3: implement** in `src/gaa/mcp/tools.py`:

Add the specs (each data tool shares this schema shape; `st_search_optimization` also allows `keyword`):
```python
    _ST_DATA_SCHEMA = {"type": "object", "properties": {
        "app_ids": {"type": "array", "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
        "labels": {"type": "array", "items": _STR},
        "start_date": _STR, "end_date": _STR,
        "countries": {"type": "array", "items": _STR},
        "metrics": {"type": "array", "items": _STR},
        "refresh": {"type": "boolean"}}}
```
(Define `_ST_DATA_SCHEMA` at module scope, then reference it.) Add to `_SPECS`:
```python
    "st_app_performance": ("Sensor Tower app downloads/revenue/active-users/retention/engagement for one or more games (app_ids and/or profile labels).", _ST_DATA_SCHEMA),
    "st_unified_app_performance": ("Sensor Tower cross-platform unified app performance.", _ST_DATA_SCHEMA),
    "st_download_channel": ("Sensor Tower organic-vs-paid download attribution.", _ST_DATA_SCHEMA),
    "st_app_store": ("Sensor Tower app-store ranks/ratings/reviews.", _ST_DATA_SCHEMA),
    "st_search_optimization": ("Sensor Tower ASO: keyword rank/difficulty/visibility (supports a `keyword` list).",
                               {"type": "object", "properties": {**_ST_DATA_SCHEMA["properties"], "keyword": {"type": "array", "items": _STR}}}),
    "st_set_app_id": ("Remember a Sensor Tower app id under a label on the active game profile (e.g. label 'self' or 'competitor:clash').",
                      {"type": "object", "properties": {"label": _STR, "id": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "id_type": _STR}, "required": ["label", "id"]}),
```
Remove the four old `sensor_tower_status/connect/list_tools/call` entries from `_SPECS` (and the old `_run_sensor_tower`). Add module-level indirections + the handler:
```python
import time as _time
from gaa.sensortower import guard as _st_guard, cache as _st_cache, relay as _st_relay_mod, appids as _st_appids

_ST_TOOL_KEYS = {"st_app_performance", "st_unified_app_performance", "st_download_channel",
                 "st_app_store", "st_search_optimization"}

def _st_today() -> str:
    return _time.strftime("%Y-%m-%d", _time.gmtime())

def _st_relay(built: dict) -> dict:
    return _st_relay_mod.request(built)

def _st_resolver_for(ctx):
    prof = ctx.profiles.get_active()
    name = prof.name if prof else "__none__"
    return lambda label: _st_appids.resolve(ctx.settings.db_path, name, label)

def _run_st_tool(ctx, name: str, args: dict) -> dict:
    if name == "st_set_app_id":
        prof = ctx.profiles.get_active()
        if not prof:
            return {"status": "error", "error": "no_active_profile"}
        _st_appids.set_app_id(ctx.settings.db_path, prof.name, args["label"], args["id"], args.get("id_type", "app_id"))
        return {"status": "success", "label": args["label"]}
    built_out = _st_guard.build(name, args, resolver=_st_resolver_for(ctx), today=_st_today())
    if built_out.get("status") == "error":
        return built_out  # need_app_id
    built = built_out["built"]
    key = _st_cache.make_key(built)
    if not args.get("refresh"):
        hit = _st_cache.get(key, now=_time.time())
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
    _st_cache.put(key, data, end_date=built["params"]["end_date"], now=_time.time())
    return {"data": data, "cached": False, "scope_trimmed": built_out.get("scope_trimmed", [])}
```
Route in `run_tool` after `jsonschema.validate(...)`, before `actions.dispatch`:
```python
    if name in _ST_TOOL_KEYS or name == "st_set_app_id":
        result = _run_st_tool(ctx, name, arguments or {})
        if name == "st_set_app_id" and isinstance(result, dict) and result.get("status") == "success":
            try:
                persist.snapshot(ctx)
            except Exception:
                _log.exception("vStorage snapshot after st_set_app_id failed")
        return result
```
- [ ] **Step 4: run, expect PASS** — `uv run pytest tests/mcp/ -v`
- [ ] **Step 5: commit**
```bash
git add src/gaa/mcp/tools.py tests/mcp/test_run_tool.py tests/mcp/test_tool_specs.py
git commit -m "feat(sensortower): st_* browser-relay tools (guard->cache->relay) + retire direct tools"
```

---

# PHASE B — Front-door bridge (Python)

## Task B1: emit `st_request` SSE events from the pending sidecar

**Files:** Modify `src/gaa/server/openclaw_client.py`. Test: `tests/server/test_st_request_poller.py`.

Add an `st_request` poller thread (mirrors `_poll_progress`): watch `GAA_ST_REQUEST`; when a new `req_id` appears, queue `{"type":"st_request", req_id, st_tool, params}`. Wire it like the progress poller in `stream_chat` (start when `GAA_ST_REQUEST` is set).

- [ ] **Step 1: failing test** `tests/server/test_st_request_poller.py`:
```python
import json
from gaa.server.openclaw_client import RealOpenClawClient

def test_emits_st_request_when_sidecar_appears(tmp_path, monkeypatch):
    req = tmp_path / "st_request.json"
    monkeypatch.setenv("GAA_ST_REQUEST", str(req))
    # Pre-write the pending request; with no OpenClaw URL the reader errors out fast,
    # but the poller should still surface the st_request before the stream ends.
    req.write_text(json.dumps({"req_id": "R1", "st_tool": "t", "params": {"a": 1}}))
    c = RealOpenClawClient(url="http://127.0.0.1:9", progress="")  # unreachable → reader errors
    seen = []
    try:
        for ev in c.stream_chat(messages=[{"role": "user", "content": "hi"}], is_admin=False, active_run_id=None):
            seen.append(ev)
    except Exception:
        pass
    kinds = [e for e in seen if e.get("type") == "st_request"]
    assert kinds and kinds[0]["req_id"] == "R1" and kinds[0]["st_tool"] == "t"
```
> Note: if the unreachable-URL reader raises before the poller emits, adjust the test to inject a fake reader, OR construct the client with a stub `_read_stream` that sleeps briefly then sentinels. Keep the assertion: an `st_request` event with `req_id`/`st_tool` is yielded. The poller must emit each `req_id` exactly once.
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** — add to `RealOpenClawClient.__init__`:
```python
        self._st_request = os.environ.get("GAA_ST_REQUEST", "")
```
In `stream_chat`, alongside the progress poller, start an st_request poller:
```python
        st_poller = None
        if self._st_request:
            st_poller = threading.Thread(target=self._poll_st_request, args=(q, stop), daemon=True)
            st_poller.start()
```
join it in the same `finally`/cleanup as `poller`. Add the method:
```python
    def _poll_st_request(self, q: "queue.Queue", stop: threading.Event) -> None:
        last = None
        while True:
            try:
                rec = json.loads(Path(self._st_request).read_text())
            except (OSError, ValueError):
                rec = None
            if rec and rec.get("req_id") and rec["req_id"] != last:
                last = rec["req_id"]
                q.put({"type": "st_request", "req_id": rec["req_id"],
                       "st_tool": rec.get("st_tool"), "params": rec.get("params")})
            if stop.is_set():
                return
            stop.wait(0.3)
```
- [ ] **Step 4: run, expect PASS**
- [ ] **Step 5: commit**
```bash
git add src/gaa/server/openclaw_client.py tests/server/test_st_request_poller.py
git commit -m "feat(sensortower): surface pending ST request as an st_request SSE event"
```

---

## Task B2: `POST /sensor-tower/fulfill`

**Files:** Modify `src/gaa/server/app.py`. Test: extend `tests/server/test_app_routes.py`.

Bearer-gated; body `{req_id, result|error}` → write the result sidecar (`GAA_ST_RESULT`). It does NOT validate the req_id against anything (the relay's poll only accepts a matching id; stale ids simply never match), but it requires `req_id` + one of `result`/`error`.

- [ ] **Step 1: failing tests** add to `tests/server/test_app_routes.py`:
```python
def test_fulfill_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, token="t0k")
    r = client.post("/sensor-tower/fulfill", json={"req_id": "R", "result": {}})
    assert r.status_code == 401

def test_fulfill_writes_result_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_ST_RESULT", str(tmp_path / "st_result.json"))
    client, _ = _client(tmp_path, monkeypatch, token="t0k")
    r = client.post("/sensor-tower/fulfill", json={"req_id": "R1", "result": {"v": 1}},
                    headers={"authorization": "Bearer t0k"})
    assert r.status_code == 200
    import json
    rec = json.loads((tmp_path / "st_result.json").read_text())
    assert rec == {"req_id": "R1", "result": {"v": 1}}

def test_fulfill_missing_fields_422(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, token="t0k")
    r = client.post("/sensor-tower/fulfill", json={"req_id": "R1"},
                    headers={"authorization": "Bearer t0k"})
    assert r.status_code == 422
```
> If `_client`'s helper sets `GAA_CACHE_DIR` and the route defaults `GAA_ST_RESULT` under it, the explicit `monkeypatch.setenv("GAA_ST_RESULT", …)` in the test pins the path. Ensure the route reads `GAA_ST_RESULT` (default under `GAA_CACHE_DIR`).
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** — in `src/gaa/server/app.py`, add a helper near the top:
```python
def _st_result_path() -> str:
    return os.environ.get("GAA_ST_RESULT") or os.path.join(
        os.environ.get("GAA_CACHE_DIR", "data/cache"), "sensortower", "st_result.json")
```
and inside `create_app`, after `/sensor-tower/callback` (or `/upload`):
```python
    @app.post("/sensor-tower/fulfill")
    def sensor_tower_fulfill(request: Request, body: dict | None = None):
        require_token(request)
        body = body or {}
        if not body.get("req_id") or ("result" not in body and "error" not in body):
            raise HTTPException(status_code=422, detail="req_id and result|error required")
        path = _st_result_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {"req_id": body["req_id"]}
        if "result" in body:
            rec["result"] = body["result"]
        else:
            rec["error"] = body["error"]
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            import json as _json
            _json.dump(rec, f)
        os.replace(tmp, path)
        return JSONResponse({"status": "success"})
```
- [ ] **Step 4: run, expect PASS** — `uv run pytest tests/server/test_app_routes.py -v`
- [ ] **Step 5: commit**
```bash
git add src/gaa/server/app.py tests/server/test_app_routes.py
git commit -m "feat(sensortower): POST /sensor-tower/fulfill writes the result sidecar"
```

---

## Task B3: pass the sidecar paths to the gaa MCP server env

**Files:** Modify `src/gaa/server/openclaw_config.py`. Test: extend `tests/server/test_openclaw_config.py`.

The gaa MCP server process (which runs `relay.py`) and the front-door must agree on `GAA_ST_REQUEST`/`GAA_ST_RESULT`. Add them to the `gaa` server's `env` block (as `${ENV}` refs, like the existing `GAA_RUN_SIDECAR`).

- [ ] **Step 1: failing test** add to `tests/server/test_openclaw_config.py`:
```python
def test_render_includes_st_sidecar_env():
    import json
    from gaa.server.openclaw_config import render_config
    cfg = json.loads(render_config())
    env = cfg["mcp"]["servers"]["gaa"]["env"]
    assert env["GAA_ST_REQUEST"] == "${GAA_ST_REQUEST}"
    assert env["GAA_ST_RESULT"] == "${GAA_ST_RESULT}"
```
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** — in `render_config`, add to the `gaa` server `env` dict (next to `GAA_RUN_SIDECAR`):
```python
                        "GAA_ST_REQUEST": "${GAA_ST_REQUEST}",
                        "GAA_ST_RESULT": "${GAA_ST_RESULT}",
```
Also set sensible defaults in the container entrypoint (`scripts/entrypoint.sh`) so both processes share them, e.g.:
```bash
export GAA_ST_REQUEST="${GAA_ST_REQUEST:-$GAA_CACHE_DIR/sensortower/st_request.json}"
export GAA_ST_RESULT="${GAA_ST_RESULT:-$GAA_CACHE_DIR/sensortower/st_result.json}"
```
(Read `scripts/entrypoint.sh` first to match its existing export style + `GAA_CACHE_DIR` usage.)
- [ ] **Step 4: run, expect PASS**
- [ ] **Step 5: commit**
```bash
git add src/gaa/server/openclaw_config.py tests/server/test_openclaw_config.py scripts/entrypoint.sh
git commit -m "feat(sensortower): share ST sidecar paths across MCP server + front-door"
```

---

# PHASE C — Frontend (TypeScript)

> The frontend holds the O365 token and makes the actual ST call. Verify the MCP streamable-HTTP handshake against the real connector during Task C2 (CORS is open `*`). Run `cd frontend && pnpm exec tsc --noEmit` after each task.

## Task C1: ST OAuth (PKCE) helpers

**Files:** Create `frontend/lib/gaa/st-oauth.ts`. Test: `frontend/tests/gaa/st-oauth.test.ts`.

Pure helpers: PKCE verifier/challenge, build the authorize URL, exchange code→token, token get/set in `sessionStorage`, expiry check. The connector base + client_id come from `NEXT_PUBLIC_ST_BASE_URL` / `NEXT_PUBLIC_ST_CLIENT_ID` (the test run showed a usable `client_id`; DCR can be added later).

- [ ] **Step 1: failing test** `frontend/tests/gaa/st-oauth.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { makePkce, buildAuthorizeUrl, tokenIsFresh } from "@/lib/gaa/st-oauth";

describe("st-oauth", () => {
  it("makePkce returns a verifier and S256 challenge", async () => {
    const { verifier, challenge } = await makePkce();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/); // base64url, no padding
    expect(challenge).not.toContain("=");
  });
  it("buildAuthorizeUrl includes pkce + state + scope", () => {
    const url = buildAuthorizeUrl({ base: "https://h.test/st", clientId: "cid",
      redirectUri: "https://app.test/sensor-tower/connected", state: "S", challenge: "C" });
    expect(url).toContain("https://h.test/st/authorize?");
    expect(url).toContain("client_id=cid");
    expect(url).toContain("code_challenge=C");
    expect(url).toContain("code_challenge_method=S256");
    expect(url).toContain("state=S");
    expect(url).toContain("scope=openid");
  });
  it("tokenIsFresh respects expiry", () => {
    expect(tokenIsFresh({ access_token: "a", expiry: 1000 }, 900)).toBe(true);
    expect(tokenIsFresh({ access_token: "a", expiry: 1000 }, 1001)).toBe(false);
    expect(tokenIsFresh(null, 0)).toBe(false);
  });
});
```
- [ ] **Step 2: run, expect FAIL** — `cd frontend && pnpm vitest run tests/gaa/st-oauth.test.ts`
- [ ] **Step 3: implement** `frontend/lib/gaa/st-oauth.ts`:
```typescript
const b64url = (buf: ArrayBuffer) =>
  btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export type StToken = { access_token: string; refresh_token?: string; expiry: number };

export async function makePkce() {
  const bytes = crypto.getRandomValues(new Uint8Array(48));
  const verifier = b64url(bytes.buffer);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: b64url(digest) };
}

export function buildAuthorizeUrl(o: { base: string; clientId: string; redirectUri: string; state: string; challenge: string }) {
  const q = new URLSearchParams({
    response_type: "code", client_id: o.clientId, redirect_uri: o.redirectUri,
    scope: "openid", state: o.state, code_challenge: o.challenge, code_challenge_method: "S256",
  });
  return `${o.base.replace(/\/$/, "")}/authorize?${q.toString()}`;
}

export async function exchangeCode(o: { base: string; clientId: string; redirectUri: string; code: string; verifier: string }): Promise<StToken> {
  const r = await fetch(`${o.base.replace(/\/$/, "")}/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "authorization_code", code: o.code,
      redirect_uri: o.redirectUri, code_verifier: o.verifier, client_id: o.clientId }),
  });
  if (!r.ok) throw new Error(`token exchange ${r.status}`);
  const d = await r.json();
  return { access_token: d.access_token, refresh_token: d.refresh_token,
           expiry: Math.floor(Date.now() / 1000) + (d.expires_in ?? 3600) - 60 };
}

const KEY = "st_token";
export const getToken = (): StToken | null => {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; }
};
export const setToken = (t: StToken) => sessionStorage.setItem(KEY, JSON.stringify(t));
export const tokenIsFresh = (t: StToken | null, nowSec: number) => !!t && nowSec < t.expiry;
```
- [ ] **Step 4: run, expect PASS** + `pnpm exec tsc --noEmit`
- [ ] **Step 5: commit**
```bash
git add frontend/lib/gaa/st-oauth.ts frontend/tests/gaa/st-oauth.test.ts
git commit -m "feat(frontend): Sensor Tower PKCE OAuth helpers"
```

---

## Task C2: ST MCP client (execute a built request)

**Files:** Create `frontend/lib/gaa/st-client.ts`. Test: `frontend/tests/gaa/st-client.test.ts`.

`callSensorTower(token, built)` performs the MCP streamable-HTTP handshake against ST: `initialize` (capture `mcp-session-id` response header) → `tools/call` with `{name: built.st_tool, arguments: built.params}` → return the parsed tool result content. Bearer auth, JSON-RPC over POST, `Accept: application/json, text/event-stream`. **Verify the exact handshake against the live connector during this task** (CORS is `*`); the response may be a single JSON body or an SSE stream — handle both (read text, take the last `data:` JSON if event-stream).

- [ ] **Step 1: failing test** `frontend/tests/gaa/st-client.test.ts` (mock `fetch`):
```typescript
import { describe, it, expect, vi } from "vitest";
import { callSensorTower } from "@/lib/gaa/st-client";

function jsonResp(body: unknown, headers: Record<string,string> = {}) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json", ...headers } });
}

describe("callSensorTower", () => {
  it("initializes, calls the tool, returns content", async () => {
    const calls: any[] = [];
    global.fetch = vi.fn(async (url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      calls.push(rpc.method);
      if (rpc.method === "initialize")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: { protocolVersion: "x", capabilities: {} } },
                        { "mcp-session-id": "S1" });
      if (rpc.method === "tools/call")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: { content: [{ type: "text", text: "{\"rows\":1}" }] } });
      return jsonResp({});
    }) as any;
    const out = await callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "app_performance_api_v2_app_performance_get", params: { app_id: [1] } });
    expect(calls).toEqual(["initialize", "tools/call"]);
    expect(out).toEqual({ rows: 1 });   // parsed text content
  });
});
```
- [ ] **Step 2: run, expect FAIL**
- [ ] **Step 3: implement** `frontend/lib/gaa/st-client.ts`:
```typescript
import type { StToken } from "./st-oauth";

const BASE = () => (process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2").replace(/\/$/, "");

type Built = { req_id: string; st_tool: string; params: Record<string, unknown> };

async function rpc(method: string, params: unknown, token: string, sessionId?: string) {
  const headers: Record<string, string> = {
    authorization: `Bearer ${token}`,
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;
  const resp = await fetch(BASE(), {
    method: "POST", headers,
    body: JSON.stringify({ jsonrpc: "2.0", id: Math.floor(Math.random() * 1e9), method, params }),
  });
  if (!resp.ok) throw new Error(`ST ${method} ${resp.status}`);
  const sid = resp.headers.get("mcp-session-id") || sessionId;
  const text = await resp.text();
  // body is either a JSON object or an SSE stream; take the last data: line if streamed.
  const ct = resp.headers.get("content-type") || "";
  const json = ct.includes("text/event-stream")
    ? JSON.parse(text.split("\n").filter((l) => l.startsWith("data:")).pop()!.slice(5).trim())
    : JSON.parse(text);
  if (json.error) throw new Error(json.error.message || "ST rpc error");
  return { result: json.result, sessionId: sid };
}

export async function callSensorTower(token: StToken, built: Built): Promise<unknown> {
  const init = await rpc("initialize", {
    protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "gaa-frontend", version: "1" },
  }, token.access_token);
  const out = await rpc("tools/call", { name: built.st_tool, arguments: built.params },
                        token.access_token, init.sessionId);
  const content = (out.result?.content ?? []) as Array<{ type: string; text?: string }>;
  const texts = content.filter((c) => c.type === "text" && c.text).map((c) => c.text!);
  // tool output is JSON-in-text where possible; fall back to the raw text array.
  try { return JSON.parse(texts.join("")); } catch { return texts; }
}
```
> Verify against live ST from a VNG-network browser: confirm `initialize` returns an `mcp-session-id` header and `tools/call` returns text content. Adjust the SSE-vs-JSON parsing if the live shape differs. Do NOT weaken the test to pass; fix the client.
- [ ] **Step 4: run, expect PASS** + `pnpm exec tsc --noEmit`
- [ ] **Step 5: commit**
```bash
git add frontend/lib/gaa/st-client.ts frontend/tests/gaa/st-client.test.ts
git commit -m "feat(frontend): Sensor Tower MCP client (initialize + tools/call)"
```

---

## Task C3: fulfill relay route

**Files:** Create `frontend/app/api/sensor-tower/fulfill/route.ts`.

Server route: receive `{req_id, result|error}` from the browser, forward to the agent `POST /sensor-tower/fulfill` with `GAA_AGENT_TOKEN` (mirrors `app/api/upload/route.ts`).

- [ ] **Step 1: implement** `frontend/app/api/sensor-tower/fulfill/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/gaa/backend";

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || !body.req_id || (body.result === undefined && body.error === undefined)) {
    return NextResponse.json({ status: "error", error: "req_id and result|error required" }, { status: 400 });
  }
  const upstream = await fetch(`${BACKEND_URL()}/sensor-tower/fulfill`, {
    method: "POST",
    headers: { authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}`, "content-type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => null);
  if (!upstream || !upstream.ok) {
    return NextResponse.json({ status: "error", error: `backend ${upstream?.status ?? "unreachable"}` }, { status: 502 });
  }
  return NextResponse.json({ status: "success" });
}
```
- [ ] **Step 2: type-check** — `cd frontend && pnpm exec tsc --noEmit` (clean).
- [ ] **Step 3: commit**
```bash
git add frontend/app/api/sensor-tower/fulfill/route.ts
git commit -m "feat(frontend): /api/sensor-tower/fulfill relays the ST result to the agent"
```

---

## Task C4: connect callback page + Connect UI

**Files:** Create `frontend/app/sensor-tower/connected/page.tsx`, `frontend/components/gaa/sensor-tower-connect.tsx`.

- [ ] **Step 1: implement the callback page** `frontend/app/sensor-tower/connected/page.tsx` (client component): read `code`+`state` from the URL, verify `state` against the value stashed at connect start (sessionStorage), exchange the code (`exchangeCode`), `setToken`, show "connected — return to chat".
```tsx
"use client";
import { useEffect, useState } from "react";
import { exchangeCode, setToken } from "@/lib/gaa/st-oauth";

export default function Connected() {
  const [msg, setMsg] = useState("Connecting…");
  useEffect(() => {
    (async () => {
      const u = new URL(window.location.href);
      const code = u.searchParams.get("code"); const state = u.searchParams.get("state");
      const err = u.searchParams.get("error");
      if (err) return setMsg(`Connection failed: ${err}`);
      const expected = sessionStorage.getItem("st_state");
      const verifier = sessionStorage.getItem("st_verifier");
      if (!code || !state || state !== expected || !verifier) return setMsg("Connection failed: bad state.");
      try {
        const t = await exchangeCode({
          base: process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2",
          clientId: process.env.NEXT_PUBLIC_ST_CLIENT_ID || "",
          redirectUri: `${window.location.origin}/sensor-tower/connected`,
          code, verifier });
        setToken(t);
        setMsg("✅ Connected — you can return to your chat.");
      } catch (e) { setMsg(`Connection failed: ${(e as Error).message}`); }
    })();
  }, []);
  return <main style={{ fontFamily: "system-ui", maxWidth: "32rem", margin: "4rem auto", textAlign: "center" }}><h2>Sensor Tower</h2><p>{msg}</p></main>;
}
```
- [ ] **Step 2: implement the Connect button** `frontend/components/gaa/sensor-tower-connect.tsx`: on click, `makePkce()`, stash verifier+state in sessionStorage, `window.location = buildAuthorizeUrl(...)`. Show connected/disconnected status from `getToken()`/`tokenIsFresh`.
```tsx
"use client";
import { makePkce, buildAuthorizeUrl, getToken, tokenIsFresh } from "@/lib/gaa/st-oauth";

export function SensorTowerConnect() {
  const connected = tokenIsFresh(getToken(), Math.floor(Date.now() / 1000));
  const connect = async () => {
    const { verifier, challenge } = await makePkce();
    const state = crypto.randomUUID();
    sessionStorage.setItem("st_verifier", verifier);
    sessionStorage.setItem("st_state", state);
    window.location.href = buildAuthorizeUrl({
      base: process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2",
      clientId: process.env.NEXT_PUBLIC_ST_CLIENT_ID || "",
      redirectUri: `${window.location.origin}/sensor-tower/connected`, state, challenge });
  };
  return <button onClick={connect}>{connected ? "Sensor Tower ✓" : "Connect Sensor Tower"}</button>;
}
```
- [ ] **Step 3: type-check** — `pnpm exec tsc --noEmit` clean. Render the button somewhere in the chat shell (the implementer places it in the existing chat header/toolbar component, matching its patterns).
- [ ] **Step 4: commit**
```bash
git add frontend/app/sensor-tower/connected/page.tsx frontend/components/gaa/sensor-tower-connect.tsx
git commit -m "feat(frontend): Sensor Tower connect button + OAuth callback page"
```

---

## Task C5: handle `st_request` in the chat stream

**Files:** Modify `frontend/lib/gaa/sse.ts`, `frontend/components/gaa/use-gaa-chat.ts`.

When an `st_request` arrives mid-stream, fire (do NOT await in the SSE loop) a handler that: gets a fresh token → none ⇒ POST fulfill `{error:{kind:"not_connected"}}` and flag the Connect UI; else `callSensorTower` → POST fulfill `{result}` (or `{error:{kind:"upstream_error",detail}}`). The agent's relay then unblocks and more tokens stream on the same connection.

- [ ] **Step 1:** add `st_request` to the `GaaEvent` union in `frontend/lib/gaa/sse.ts`:
```typescript
  | { type: "st_request"; req_id: string; st_tool: string; params: Record<string, unknown> }
```
- [ ] **Step 2:** in `use-gaa-chat.ts`, add a handler and an `onEvent` branch:
```typescript
import { getToken, tokenIsFresh } from "@/lib/gaa/st-oauth";
import { callSensorTower } from "@/lib/gaa/st-client";

async function fulfillSensorTower(ev: { req_id: string; st_tool: string; params: Record<string, unknown> }) {
  const post = (body: unknown) =>
    fetch("/api/sensor-tower/fulfill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const token = getToken();
  if (!tokenIsFresh(token, Math.floor(Date.now() / 1000))) {
    await post({ req_id: ev.req_id, error: { kind: "not_connected" } });
    return;
  }
  try {
    const data = await callSensorTower(token!, ev);
    await post({ req_id: ev.req_id, result: data });
  } catch (e) {
    await post({ req_id: ev.req_id, error: { kind: "upstream_error", detail: (e as Error).message } });
  }
}
```
In the `readSSE` callback, add:
```typescript
        } else if (e.type === "st_request") {
          void fulfillSensorTower(e as any);
        }
```
- [ ] **Step 3: type-check** — `pnpm exec tsc --noEmit` clean. (Optional vitest: assert `fulfillSensorTower` posts `not_connected` when `getToken()` is null — mock `fetch` + `sessionStorage`.)
- [ ] **Step 4: commit**
```bash
git add frontend/lib/gaa/sse.ts frontend/components/gaa/use-gaa-chat.ts
git commit -m "feat(frontend): fulfill st_request events via the browser ST client"
```

---

# PHASE D — Wiring, playbook, acceptance

## Task D1: agent playbook (AGENTS.md)

**Files:** Modify `openclaw/AGENTS.md` (replace the prior `## Sensor Tower` section).

- [ ] **Step 1:** replace the Sensor Tower section with the browser-proxy playbook:
```markdown
## Sensor Tower (market data, multi-game)
You can pull live Sensor Tower data (downloads, revenue, retention, ranks, ASO) for one or more
games — via the user's browser (they click "Connect Sensor Tower" once per session).
- Tools: `st_app_performance`, `st_unified_app_performance`, `st_download_channel`, `st_app_store`,
  `st_search_optimization`. Pass `app_ids` and/or profile `labels` (e.g. ["self","competitor:clash"])
  plus an optional date range; defaults and budget caps are applied for you.
- If a tool returns `need_app_id`, ask the user for the Sensor Tower app id for the named label,
  then call `st_set_app_id(label, id)` to remember it before retrying.
- If a tool returns `not_connected`, tell the user to click "Connect Sensor Tower", then retry the
  same call after they confirm.
- If a result has `scope_trimmed`, mention what was narrowed (e.g. fewer countries) to stay within
  the data budget. `cached: true` means it was served from cache (free, instant).
- On `upstream_error`/`fulfill_timeout`, say Sensor Tower is unavailable and continue the analysis
  without it — ST is enrichment, never required. Never paste tokens.
```
- [ ] **Step 2: commit**
```bash
git add openclaw/AGENTS.md
git commit -m "feat(sensortower): browser-proxy connect+use playbook"
```

## Task D2: full suite + acceptance

- [ ] **Step 1:** `uv run pytest -q` → all green.
- [ ] **Step 2:** `cd frontend && pnpm vitest run && pnpm exec tsc --noEmit` → green.
- [ ] **Step 3: env to set at deploy** — frontend: `NEXT_PUBLIC_ST_BASE_URL` (default staging), `NEXT_PUBLIC_ST_CLIENT_ID` (a registered ST public client whose redirect_uri is `<frontend>/sensor-tower/connected`); agent/container: `GAA_ST_REQUEST`/`GAA_ST_RESULT` (entrypoint defaults). Document in README.
- [ ] **Step 4: live smoke (VNG-network browser)** — Connect Sensor Tower → onboard/select a game → set an app id (`st_set_app_id` or via chat) → ask for performance → confirm an `st_request` fires, the browser fetches, the agent returns real data; ask again → confirm `cached: true`. Record the result.

---

## Self-Review notes

- **Spec coverage:** browser-proxy relay (A5/B1/B2/C5), full+guardrails (A4), global cache (A2/A3, hit short-circuits in A6), app-IDs ask-then-persist (A1/A6 `st_set_app_id` + guard resolution), multi-game (`app_ids`/`labels`, ≤10 cap in A4), error contracts (A6 maps need_app_id/not_connected/upstream_error/fulfill_timeout; scope_trimmed surfaced), security (token browser-only via C1/C4; bearer-gated fulfill B2; PKCE+state C4), retire-old-direct-tools (A6), testing (every Python task TDD; frontend vitest + tsc; live smoke D2). Out-of-scope items (fetch_report, name→ID, concurrent multi-user, retiring dormant Python) match the spec.
- **Type/contract consistency:** the shared relay contract (built request, `st_request` event, fulfill body, result sidecar) is used identically by `relay.py` (A5), the poller (B1), `/fulfill` (B2), `st-client.ts`/`use-gaa-chat.ts` (C2/C5). `make_key`/`get`/`put` signatures match between A2 and A6. Guard returns `{built}` / `{status:error,error:need_app_id,labels}` consumed in A6.
- **No placeholders:** every code step is complete; the two "verify against live ST" notes (C2 handshake) and "match entrypoint style" (B3) are deliberate verification steps, not missing code.
