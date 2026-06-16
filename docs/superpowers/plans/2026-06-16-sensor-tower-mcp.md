# Sensor Tower MCP — Conversational Connect & Proxy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the GAA agent pull live Sensor Tower market data by walking the user through a self-service O365 OAuth connect mid-chat, then proxying Sensor Tower's MCP tools.

**Architecture:** A new framework-free `gaa/sensortower/` package (`config`, `store`, `oauth`, `client`) makes the in-process `gaa` MCP server an MCP *client* of Sensor Tower. Four always-present tools (`sensor_tower_status`, `sensor_tower_connect`, `sensor_tower_list_tools`, `sensor_tower_call`) let the agent drive the OAuth flow and forward calls with the connected session's token. The Vercel frontend gains a `/api/sensor-tower/callback` route that relays the OAuth `code` server-to-server to a new bearer-gated `POST /sensor-tower/callback` on the agent. Tokens persist via the existing vStorage snapshot mechanism.

**Tech Stack:** Python 3.11, `mcp` SDK (`streamablehttp_client` + `ClientSession`), `httpx`, `jsonschema`, FastAPI, pytest; Next.js (App Router, TypeScript) for the frontend route.

> **Spec deviation (deliberate):** The spec describes proxying ST tools as per-tool `st__<tool>` entries. OpenClaw lists the `gaa` server's tools once at conversation start, so dynamically-added per-tool entries would not be visible in the same conversation the user connects in. Phase 1a therefore ships a **generic passthrough** (`sensor_tower_list_tools` + `sensor_tower_call`) that is always present and works immediately after connect. Per-tool `st__*` schemas remain a documented fast-follow (Task 11, optional) once Task 0 confirms whether OpenClaw re-lists tools mid-conversation.

---

## File Structure

**New (Python):**
- `src/gaa/sensortower/__init__.py` — package marker.
- `src/gaa/sensortower/config.py` — env-driven settings (ST base URL, redirect URI) + well-known discovery URL helper. One responsibility: where ST lives.
- `src/gaa/sensortower/store.py` — durable token store + pending-connect store under `GAA_CACHE_DIR/sensortower/`. One responsibility: persisted state.
- `src/gaa/sensortower/oauth.py` — the OAuth 2.1 dance (DCR, authorize-URL, code exchange, refresh) over `httpx`. One responsibility: the protocol.
- `src/gaa/sensortower/client.py` — the ST MCP client (background asyncio loop + per-call short-lived session, refresh-on-401). One responsibility: talking MCP to ST.

**Modified (Python):**
- `src/gaa/persist.py` — add the token store file to `_durable_items`.
- `src/gaa/mcp/tools.py` — add the four `sensor_tower_*` specs + route them in `run_tool`.
- `src/gaa/server/app.py` — add `POST /sensor-tower/callback`.

**New (frontend):**
- `frontend/app/api/sensor-tower/callback/route.ts` — browser-redirect catcher → relays `{code,state}` to the agent → renders a "connected" page.

**Modified (other):**
- The agent persona/SOUL seed (the connect playbook) — Task 10.
- `docs/` env notes for the new vars — Task 9.

**Tests (new/extended):**
- `tests/sensortower/__init__.py`, `test_config.py`, `test_store.py`, `test_oauth.py`, `test_client.py`
- `tests/test_persist.py` (extend)
- `tests/mcp/test_tool_specs.py`, `tests/mcp/test_run_tool.py` (extend)
- `tests/server/test_app_routes.py` (extend)

---

## Task 0: Phase-0 de-risk spike (manual gate — do this first)

**Goal:** Prove the three unknowns before writing code. No production code is written in this task; it produces facts that the later tasks depend on.

**Files:** none (uses `../Random/TestMCP/test_mcp.py`).

- [ ] **Step 1: Confirm the deployed runtime can reach the ST host.**

Get a shell on the deployed `gaa-custom-agent` (or run an equivalent probe from it) and run:

```bash
curl -sS -m 15 -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST "https://stg-aawp-connector.vnggames.net/sensor-tower-v2" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

Expected: `HTTP 401` (reachable, unauthenticated). **If it times out / fails to connect**, the PUBLIC runtime is firewalled from the ST host → STOP and escalate: the agent must move to VPC mode (`/agentbase-deploy` network mode) before this feature is viable. Record the result.

- [ ] **Step 2: Enumerate ST tools + confirm an `https` redirect_uri registers.**

On a machine with a browser + VNG O365, edit `../Random/TestMCP/test_mcp.py`'s `CALLBACK_URL`/`redirect_uris` to a throwaway `https` URL to confirm DCR accepts non-localhost redirects, then run the full test to list tools:

```bash
cd ../Random/TestMCP && python test_mcp.py
```

Expected: OAuth completes; `[full] TONG CONG N tool(s)` lists the ST tools with names + descriptions. **Capture the full tool list + each tool's `inputSchema`** into `docs/superpowers/specs/sensor-tower-tools.md` — Task 11 and the Phase-1b enrichment depend on it.

- [ ] **Step 3: Confirm whether OpenClaw re-lists `gaa` tools mid-conversation.**

In a local run of the combined image, watch the `gaa` MCP server's `list_tools` calls (add a temporary `_log.info` in `src/gaa/mcp/server.py` `list_tools`) across a multi-turn conversation. Record: is `list_tools` called once per conversation, or per turn? This decides whether Task 11 (`st__*` per-tool) is worth doing. Remove the temporary log afterward.

- [ ] **Step 4: Decision gate.** Record outcomes in the plan PR description. Proceed to Task 1 only if Step 1 passed (reachable, or VPC plan made).

---

## Task 1: `gaa/sensortower/config.py` — settings

**Files:**
- Create: `src/gaa/sensortower/__init__.py` (empty)
- Create: `src/gaa/sensortower/config.py`
- Test: `tests/sensortower/__init__.py` (empty), `tests/sensortower/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/sensortower/test_config.py
from gaa.sensortower import config

def test_defaults_point_at_staging(monkeypatch):
    monkeypatch.delenv("GAA_ST_BASE_URL", raising=False)
    assert config.base_url() == "https://stg-aawp-connector.vnggames.net/sensor-tower-v2"

def test_base_url_override(monkeypatch):
    monkeypatch.setenv("GAA_ST_BASE_URL", "https://example.test/mcp")
    assert config.base_url() == "https://example.test/mcp"

def test_well_known_url_is_host_root_with_resource_suffix(monkeypatch):
    monkeypatch.setenv("GAA_ST_BASE_URL", "https://h.test/sensor-tower-v2")
    assert config.well_known_url() == \
        "https://h.test/.well-known/oauth-authorization-server/sensor-tower-v2"

def test_redirect_uri_from_env(monkeypatch):
    monkeypatch.setenv("GAA_ST_REDIRECT_URI", "https://app.test/api/sensor-tower/callback")
    assert config.redirect_uri() == "https://app.test/api/sensor-tower/callback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sensortower/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: gaa.sensortower`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/sensortower/config.py
"""Where Sensor Tower lives. All values overridable by env for tests/other tiers."""
from __future__ import annotations

import os
from urllib.parse import urlparse

_DEFAULT_BASE = "https://stg-aawp-connector.vnggames.net/sensor-tower-v2"


def base_url() -> str:
    return os.environ.get("GAA_ST_BASE_URL", _DEFAULT_BASE).rstrip("/")


def well_known_url() -> str:
    """RFC 8414 metadata lives at the HOST root with the resource path as suffix."""
    p = urlparse(base_url())
    return f"{p.scheme}://{p.netloc}/.well-known/oauth-authorization-server{p.path}"


def redirect_uri() -> str:
    return os.environ.get("GAA_ST_REDIRECT_URI", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/sensortower/test_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sensortower/__init__.py src/gaa/sensortower/config.py tests/sensortower/__init__.py tests/sensortower/test_config.py
git commit -m "feat(sensortower): config module (base url, well-known, redirect)"
```

---

## Task 2: `gaa/sensortower/store.py` — token + pending-connect store

**Files:**
- Create: `src/gaa/sensortower/store.py`
- Test: `tests/sensortower/test_store.py`

State shapes (used by later tasks — keep these names exact):
- token record: `{"access_token": str, "refresh_token": str, "expiry": float}` keyed by `session`.
- pending record: `{"code_verifier": str, "session": str, "ts": float}` keyed by `state`.
- client creds: `{"client_id": str, "client_secret": str, "expires_at": float}` (app-level, single key `"_client"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/sensortower/test_store.py
import os, stat
from gaa.sensortower import store

def _dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))

def test_token_round_trip(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "a", "refresh_token": "r", "expiry": 123.0})
    assert store.get_tokens("default")["access_token"] == "a"
    assert store.get_tokens("missing") is None

def test_clear_tokens(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_tokens("s", {"access_token": "a", "refresh_token": "r", "expiry": 1.0})
    store.clear_tokens("s")
    assert store.get_tokens("s") is None

def test_pending_round_trip_and_pop_is_single_use(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_pending("st8", {"code_verifier": "v", "session": "default", "ts": 100.0})
    rec = store.pop_pending("st8")
    assert rec["code_verifier"] == "v"
    assert store.pop_pending("st8") is None  # consumed

def test_client_creds_round_trip(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    assert store.get_client() is None
    store.set_client({"client_id": "c", "client_secret": "s", "expires_at": 0.0})
    assert store.get_client()["client_id"] == "c"

def test_file_is_0600(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_tokens("s", {"access_token": "a", "refresh_token": "r", "expiry": 1.0})
    mode = stat.S_IMODE(os.stat(store.store_path()).st_mode)
    assert mode == 0o600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sensortower/test_store.py -v`
Expected: FAIL (`AttributeError`/`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/sensortower/store.py
"""Durable Sensor Tower state: per-session tokens, pending OAuth states, app client creds.

Lives under GAA_CACHE_DIR/sensortower/state.json (mode 0600) and is added to
persist._durable_items so it snapshots to vStorage. Values are never logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _dir() -> Path:
    d = Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower"
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_path() -> str:
    return str(_dir() / "state.json")


def _read() -> dict:
    try:
        with open(store_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    path = store_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def get_tokens(session: str):
    return _read().get("tokens", {}).get(session)


def set_tokens(session: str, rec: dict) -> None:
    d = _read(); d.setdefault("tokens", {})[session] = rec; _write(d)


def clear_tokens(session: str) -> None:
    d = _read(); d.get("tokens", {}).pop(session, None); _write(d)


def set_pending(state: str, rec: dict) -> None:
    d = _read(); d.setdefault("pending", {})[state] = rec; _write(d)


def pop_pending(state: str):
    d = _read(); rec = d.get("pending", {}).pop(state, None); _write(d); return rec


def get_client():
    return _read().get("client")


def set_client(rec: dict) -> None:
    d = _read(); d["client"] = rec; _write(d)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/sensortower/test_store.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sensortower/store.py tests/sensortower/test_store.py
git commit -m "feat(sensortower): durable token + pending-connect + client store"
```

---

## Task 3: Persist the token store across restarts

**Files:**
- Modify: `src/gaa/persist.py` (the `_durable_items` list)
- Test: `tests/test_persist.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_persist.py  (add this test)
def test_durable_items_include_sensortower_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    from gaa.cli.wiring import build_context
    from gaa.core.llm.client import FakeLLM
    from gaa import persist
    from gaa.sensortower import store
    ctx = build_context(llm=FakeLLM({}))
    store.set_tokens("default", {"access_token": "a", "refresh_token": "r", "expiry": 1.0})
    arcnames = {arc for arc, _path, _is_dir in persist._durable_items(ctx)}
    assert "sensortower_state.json" in arcnames
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_persist.py::test_durable_items_include_sensortower_state -v`
Expected: FAIL (`assert 'sensortower_state.json' in arcnames`).

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/persist.py`, inside `_durable_items`, add the sensortower store next to the extensions entries:

```python
    from gaa.server import extensions
    from gaa.sensortower import store as st_store
    return [
        ("config.toml", Path(ctx.config._path), False),
        ("profiles.sqlite", Path(ctx.settings.db_path), False),
        ("metrics", cache / "metrics", True),
        ("tools", tools, True),
        ("openclaw_workspace", openclaw_home / "workspace", True),
        ("mcp_registry.json", Path(extensions.registry_path()), False),
        ("mcp_secrets.json", Path(extensions.secrets_path()), False),
        ("sensortower_state.json", Path(st_store.store_path()), False),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_persist.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/persist.py tests/test_persist.py
git commit -m "feat(sensortower): snapshot token store to vStorage (durable across restart)"
```

---

## Task 4: `gaa/sensortower/oauth.py` — the OAuth dance

**Files:**
- Create: `src/gaa/sensortower/oauth.py`
- Test: `tests/sensortower/test_oauth.py`

Public functions (exact signatures used by Tasks 5 & 6):
- `ensure_client() -> dict` — register via DCR if no valid stored client; returns client creds.
- `build_authorize_url(session: str, *, now: float) -> str` — stores pending state, returns the URL.
- `exchange_code(code: str, state: str, *, now: float) -> dict` — validates state, exchanges, stores tokens under the session; returns the token record.
- `valid_access_token(session: str, *, now: float) -> str | None` — returns a non-expired access token, refreshing if needed; `None` if not connected / refresh failed.
- `endpoints() -> dict` — discovery (cached): `{"authorization_endpoint","token_endpoint","registration_endpoint"}`.

- [ ] **Step 1: Write the failing test** (mock `httpx` via a fake transport)

```python
# tests/sensortower/test_oauth.py
import httpx, pytest
from gaa.sensortower import oauth, store, config

DISC = {
    "authorization_endpoint": "https://h.test/sensor-tower-v2/authorize",
    "token_endpoint": "https://h.test/sensor-tower-v2/token",
    "registration_endpoint": "https://h.test/sensor-tower-v2/register",
}

@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_ST_BASE_URL", "https://h.test/sensor-tower-v2")
    monkeypatch.setenv("GAA_ST_REDIRECT_URI", "https://app.test/api/sensor-tower/callback")
    oauth._ENDPOINTS_CACHE.clear()

def _mount(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def factory(*a, **k):
        k["transport"] = transport
        return real_client(*a, **k)
    monkeypatch.setattr(oauth.httpx, "Client", factory)

def test_ensure_client_registers_once(monkeypatch):
    calls = {"register": 0}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/oauth-authorization-server/sensor-tower-v2"):
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            calls["register"] += 1
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    c1 = oauth.ensure_client(); c2 = oauth.ensure_client()
    assert c1["client_id"] == "cid" and calls["register"] == 1  # cached second time

def test_authorize_url_has_pkce_and_state(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    url = oauth.build_authorize_url("default", now=1000.0)
    assert url.startswith("https://h.test/sensor-tower-v2/authorize?")
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "state=" in url and "client_id=cid" in url
    # a pending row was written
    import urllib.parse as up
    state = up.parse_qs(up.urlparse(url).query)["state"][0]
    assert store.pop_pending(state)["session"] == "default"

def test_exchange_code_stores_tokens(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    url = oauth.build_authorize_url("default", now=1000.0)
    import urllib.parse as up
    state = up.parse_qs(up.urlparse(url).query)["state"][0]
    rec = oauth.exchange_code("CODE", state, now=1000.0)
    assert rec["access_token"] == "AT"
    assert store.get_tokens("default")["expiry"] == 1000.0 + 3600 - 60

def test_exchange_code_rejects_unknown_state(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    with pytest.raises(ValueError):
        oauth.exchange_code("CODE", "bogus", now=1.0)

def test_valid_access_token_refreshes_when_expired(monkeypatch):
    store.set_client({"client_id": "cid", "client_secret": "sec", "expires_at": 0.0})
    store.set_tokens("default", {"access_token": "OLD", "refresh_token": "RT", "expiry": 500.0})
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    tok = oauth.valid_access_token("default", now=1000.0)  # now > expiry 500 → refresh
    assert tok == "NEW"
    assert store.get_tokens("default")["refresh_token"] == "RT2"

def test_valid_access_token_none_when_refresh_fails(monkeypatch):
    store.set_client({"client_id": "cid", "client_secret": "sec", "expires_at": 0.0})
    store.set_tokens("default", {"access_token": "OLD", "refresh_token": "RT", "expiry": 1.0})
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/token"):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    assert oauth.valid_access_token("default", now=1000.0) is None
    assert store.get_tokens("default") is None  # cleared
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sensortower/test_oauth.py -v`
Expected: FAIL (module/attr errors).

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/sensortower/oauth.py
"""OAuth 2.1 (auth-code + PKCE + refresh + DCR) against the Sensor Tower connector.

We drive the dance by hand (not the MCP SDK's inline OAuthClientProvider) because our
login spans multiple chat turns and a real web callback, not one blocking connection.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import urllib.parse as _up

import httpx

from gaa.sensortower import config, store

_log = logging.getLogger(__name__)
_ENDPOINTS_CACHE: dict[str, dict] = {}
_TIMEOUT = 15.0
_REFRESH_MARGIN_S = 60


def endpoints() -> dict:
    if "v" not in _ENDPOINTS_CACHE:
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.get(config.well_known_url())
            r.raise_for_status()
            _ENDPOINTS_CACHE["v"] = r.json()
    return _ENDPOINTS_CACHE["v"]


def ensure_client() -> dict:
    existing = store.get_client()
    if existing and existing.get("client_id"):
        return existing
    body = {
        "client_name": "GAA Sensor Tower Connector",
        "redirect_uris": [config.redirect_uri()],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.post(endpoints()["registration_endpoint"], json=body)
        r.raise_for_status()
        data = r.json()
    rec = {"client_id": data["client_id"],
           "client_secret": data.get("client_secret", ""),
           "expires_at": float(data.get("client_secret_expires_at", 0) or 0)}
    store.set_client(rec)
    return rec


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(session: str, *, now: float) -> str:
    client = ensure_client()
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    store.set_pending(state, {"code_verifier": verifier, "session": session, "ts": now})
    q = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": config.redirect_uri(),
        "scope": "openid",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return endpoints()["authorization_endpoint"] + "?" + _up.urlencode(q)


def _token_request(form: dict) -> dict:
    client = ensure_client()
    form = {**form, "client_id": client["client_id"], "client_secret": client["client_secret"]}
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.post(endpoints()["token_endpoint"], data=form)
        r.raise_for_status()
        return r.json()


def exchange_code(code: str, state: str, *, now: float) -> dict:
    pending = store.pop_pending(state)
    if not pending:
        raise ValueError("unknown or expired state")
    data = _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri(),
        "code_verifier": pending["code_verifier"],
    })
    rec = {"access_token": data["access_token"],
           "refresh_token": data.get("refresh_token", ""),
           "expiry": now + float(data.get("expires_in", 3600)) - _REFRESH_MARGIN_S}
    store.set_tokens(pending["session"], rec)
    return rec


def valid_access_token(session: str, *, now: float) -> str | None:
    rec = store.get_tokens(session)
    if not rec:
        return None
    if now < rec["expiry"]:
        return rec["access_token"]
    # expired → refresh
    if not rec.get("refresh_token"):
        store.clear_tokens(session)
        return None
    try:
        data = _token_request({"grant_type": "refresh_token", "refresh_token": rec["refresh_token"]})
    except httpx.HTTPError:
        _log.info("sensor tower refresh failed for session=%s; clearing", session)
        store.clear_tokens(session)
        return None
    new = {"access_token": data["access_token"],
           "refresh_token": data.get("refresh_token") or rec["refresh_token"],
           "expiry": now + float(data.get("expires_in", 3600)) - _REFRESH_MARGIN_S}
    store.set_tokens(session, new)
    return new["access_token"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/sensortower/test_oauth.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sensortower/oauth.py tests/sensortower/test_oauth.py
git commit -m "feat(sensortower): OAuth dance (DCR, PKCE authorize, exchange, refresh)"
```

---

## Task 5: `gaa/sensortower/client.py` — the ST MCP client

**Files:**
- Create: `src/gaa/sensortower/client.py`
- Test: `tests/sensortower/test_client.py`

Public functions (exact signatures used by Task 6):
- `list_tools(access_token: str) -> list[dict]` — `[{"name","description","input_schema"}]`.
- `call_tool(access_token: str, name: str, arguments: dict) -> dict` — `{"content": [str, ...]}`.

These open a short-lived `streamablehttp_client` session per call with a static `Authorization: Bearer` header (token managed by `oauth`), run on a shared background event loop so the sync caller can block on the result.

- [ ] **Step 1: Write the failing test** (against a real in-process MCP server over an in-memory stream — reuse the SDK's memory transport)

```python
# tests/sensortower/test_client.py
from contextlib import asynccontextmanager
import mcp.types as types
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session as _connect
from gaa.sensortower import client as st_client

def _fake_st_server() -> Server:
    srv = Server("fake-st")
    @srv.list_tools()
    async def _lt():
        return [types.Tool(name="get_app", description="Get app stats",
                           inputSchema={"type": "object", "properties": {"id": {"type": "string"}}})]
    @srv.call_tool()
    async def _ct(name, arguments):
        return [types.TextContent(type="text", text=f"{name}:{arguments.get('id')}")]
    return srv

def _patch_open_session(monkeypatch):
    # _open_session must be an async CM yielding a started ClientSession; _connect already is.
    @asynccontextmanager
    async def fake_open_session(_token):
        async with _connect(_fake_st_server()) as session:
            yield session
    monkeypatch.setattr(st_client, "_open_session", fake_open_session)

def test_list_tools_maps_schema(monkeypatch):
    _patch_open_session(monkeypatch)
    tools = st_client.list_tools("AT")
    assert tools == [{"name": "get_app", "description": "Get app stats",
                      "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}}}]

def test_call_tool_returns_text_content(monkeypatch):
    _patch_open_session(monkeypatch)
    out = st_client.call_tool("AT", "get_app", {"id": "42"})
    assert out["content"] == ["get_app:42"]
```

> Implementation note: `_open_session(token)` is an `@asynccontextmanager` yielding an initialized `ClientSession`. In production it wraps `streamablehttp_client(config.base_url(), headers={"Authorization": f"Bearer {token}"})` + `ClientSession`; the test substitutes one wrapping the in-memory `create_connected_server_and_client_session` (itself an async CM yielding a started session). Keep `list_tools`/`call_tool` thin so they work with both.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sensortower/test_client.py -v`
Expected: FAIL (module/attr errors).

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/sensortower/client.py
"""Sensor Tower MCP client. A shared background asyncio loop lets the sync MCP-tool
dispatch (gaa.mcp.tools.run_tool) block on async ST calls. One short-lived ST session
per call keeps lifecycle trivial; the access token is managed by gaa.sensortower.oauth.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from gaa.sensortower import config

_loop = None
_lock = threading.Lock()


def _bg_loop():
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop


def _run(coro, timeout=60):
    return asyncio.run_coroutine_threadsafe(coro, _bg_loop()).result(timeout)


@asynccontextmanager
async def _open_session(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(config.base_url(), headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def list_tools(access_token: str) -> list[dict]:
    async def _go():
        async with _open_session(access_token) as session:
            result = await session.list_tools()
            return [{"name": t.name, "description": t.description or "",
                     "input_schema": t.inputSchema} for t in result.tools]
    return _run(_go())


def call_tool(access_token: str, name: str, arguments: dict) -> dict:
    async def _go():
        async with _open_session(access_token) as session:
            result = await session.call_tool(name, arguments or {})
            texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
            return {"content": texts, "is_error": bool(getattr(result, "isError", False))}
    return _run(_go())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/sensortower/test_client.py -v`
Expected: PASS (2 passed).

> If the monkeypatched `_open_session` shape needs adjusting to satisfy `async with`, wrap the test's fake in `@asynccontextmanager`; the production code already is one. Keep the public `list_tools`/`call_tool` signatures unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sensortower/client.py tests/sensortower/test_client.py
git commit -m "feat(sensortower): MCP client (bg loop, per-call session, schema map)"
```

---

## Task 6: Wire the four tools into the `gaa` MCP server

**Files:**
- Modify: `src/gaa/mcp/tools.py`
- Test: `tests/mcp/test_tool_specs.py` (extend), `tests/mcp/test_run_tool.py` (extend)

The four tools (all static, always listed):
- `sensor_tower_status` → `{connected: bool, expires_in: number|null}` for the session (default `"default"`).
- `sensor_tower_connect` → `{authorize_url: str, message: str}`.
- `sensor_tower_list_tools` → `{tools: [...]}` or `{status:"error", error:"not_connected"}`.
- `sensor_tower_call` → forwards `{tool, arguments}`; `not_connected`/`upstream_error` on failure.

- [ ] **Step 1: Write the failing tests**

```python
# tests/mcp/test_run_tool.py  (add)
import time
from gaa.mcp import tools as mcp_tools
from gaa.sensortower import store

def _ctx_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "g.sqlite"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "g.toml"))
    from gaa.cli.wiring import build_context
    from gaa.core.llm.client import FakeLLM
    return build_context(llm=FakeLLM({}))

def test_status_reports_disconnected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    out = mcp_tools.run_tool(ctx, "sensor_tower_status", {}, is_admin=False)
    assert out["connected"] is False

def test_status_reports_connected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "a", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    out = mcp_tools.run_tool(ctx, "sensor_tower_status", {}, is_admin=False)
    assert out["connected"] is True and out["expires_in"] > 0

def test_connect_returns_authorize_url(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_build_authorize_url",
                        lambda session: "https://h.test/authorize?state=x")
    out = mcp_tools.run_tool(ctx, "sensor_tower_connect", {}, is_admin=False)
    assert out["authorize_url"].startswith("https://h.test/authorize")

def test_list_tools_not_connected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    out = mcp_tools.run_tool(ctx, "sensor_tower_list_tools", {}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "not_connected"

def test_call_forwards_when_connected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "AT", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    monkeypatch.setattr(mcp_tools, "_st_call_tool",
                        lambda token, name, args: {"content": [f"{name}:{args}"]})
    out = mcp_tools.run_tool(ctx, "sensor_tower_call",
                             {"tool": "get_app", "arguments": {"id": "1"}}, is_admin=False)
    assert out["content"] == ["get_app:{'id': '1'}"]
```

```python
# tests/mcp/test_tool_specs.py  (add)
def test_specs_include_sensor_tower_tools():
    names = {t["name"] for t in __import__("gaa.mcp.tools", fromlist=["tools"]).tool_specs(is_admin=False)}
    assert {"sensor_tower_status", "sensor_tower_connect",
            "sensor_tower_list_tools", "sensor_tower_call"} <= names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_run_tool.py tests/mcp/test_tool_specs.py -v`
Expected: FAIL (`unknown tool: 'sensor_tower_status'` etc.).

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/mcp/tools.py`, add to `_SPECS`:

```python
    "sensor_tower_status": ("Check whether Sensor Tower is connected for this session (no login required to call).",
                            {"type": "object", "properties": {"session": _STR}}),
    "sensor_tower_connect": ("Begin connecting Sensor Tower: returns an O365 login URL to show the user. After they log in, the connection completes automatically; poll sensor_tower_status to confirm.",
                             {"type": "object", "properties": {"session": _STR}}),
    "sensor_tower_list_tools": ("List the Sensor Tower tools available once connected.",
                                {"type": "object", "properties": {"session": _STR}}),
    "sensor_tower_call": ("Call a Sensor Tower tool by name with its arguments (requires a connected session).",
                          {"type": "object",
                           "properties": {"tool": _STR, "arguments": {"type": "object"}, "session": _STR},
                           "required": ["tool"]}),
```

Add module-level indirections (so tests can monkeypatch without importing httpx/mcp):

```python
import time as _time
from gaa.sensortower import oauth as _st_oauth, client as _st_client, store as _st_store

def _st_build_authorize_url(session: str) -> str:
    return _st_oauth.build_authorize_url(session, now=_time.time())

def _st_valid_token(session: str):
    return _st_oauth.valid_access_token(session, now=_time.time())

def _st_call_tool(token: str, name: str, arguments: dict) -> dict:
    return _st_client.call_tool(token, name, arguments)

def _st_list_tools(token: str) -> list[dict]:
    return _st_client.list_tools(token)
```

Add a router inside `run_tool` **after** the `jsonschema.validate(arguments, schema)` block and **before** the `actions.dispatch(...)` line (so args are schema-validated, but these tools never reach `actions.dispatch`, which has no `sensor_tower_*` handler):

```python
    # (immediately after the jsonschema.validate(...) try/except, before actions.dispatch)
    if name.startswith("sensor_tower_"):
        return _run_sensor_tower(name, arguments or {})
```

And the handler (place after `run_tool`):

```python
def _run_sensor_tower(name: str, args: dict) -> dict:
    session = args.get("session") or "default"
    if name == "sensor_tower_status":
        tok = _st_valid_token(session)
        rec = _st_store.get_tokens(session) if tok is not None else None
        return {"connected": tok is not None,
                "expires_in": (rec["expiry"] - _time.time()) if rec else None}
    if name == "sensor_tower_connect":
        try:
            url = _st_build_authorize_url(session)
        except Exception as exc:  # discovery/registration failure
            _log.exception("sensor_tower_connect failed")
            return {"status": "error", "error": "connect_failed", "detail": str(exc)}
        return {"authorize_url": url,
                "message": "Open this link, sign in with your VNG O365 account, then return here. "
                           "I'll confirm once you're connected."}
    tok = _st_valid_token(session)
    if tok is None:
        return {"status": "error", "error": "not_connected",
                "hint": "Call sensor_tower_connect and ask the user to finish the O365 login."}
    try:
        if name == "sensor_tower_list_tools":
            return {"tools": _st_list_tools(tok)}
        if name == "sensor_tower_call":
            if not args.get("tool"):
                return {"status": "error", "error": "bad_args", "detail": "'tool' is required"}
            return _st_call_tool(tok, args["tool"], args.get("arguments") or {})
    except Exception as exc:
        _log.exception("sensor tower upstream call failed")
        return {"status": "error", "error": "upstream_error", "detail": str(exc)}
    return {"status": "error", "error": f"unknown tool: {name!r}"}
```

> Note: `sensor_tower_*` tools are **not** in `actions.ADMIN_ACTIONS`/`MUTATING_ACTIONS`, so they are non-admin and don't trigger a vStorage snapshot here; the token store snapshots itself via `oauth`/`store` writes + the entrypoint restore (Task 3 made the file durable). The `jsonschema.validate` path still applies because the specs are in `_SPECS` — keep the early `startswith` router *after* schema validation if you want args validated; for `sensor_tower_call` the schema requires `tool`, which is sufficient. (Place the router after the `jsonschema.validate(...)` block.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/ -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/mcp/tools.py tests/mcp/test_run_tool.py tests/mcp/test_tool_specs.py
git commit -m "feat(sensortower): status/connect/list/call tools on the gaa MCP server"
```

---

## Task 7: `POST /sensor-tower/callback` on the front door

**Files:**
- Modify: `src/gaa/server/app.py`
- Test: `tests/server/test_app_routes.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_app_routes.py  (add; reuse the module's _client helper)
def test_sensor_tower_callback_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, token="t0k")
    r = client.post("/sensor-tower/callback", json={"code": "c", "state": "s"})
    assert r.status_code == 401

def test_sensor_tower_callback_exchanges_and_acks(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, token="t0k")
    import gaa.server.app as appmod
    called = {}
    def fake_exchange(code, state, *, now):
        called["code"], called["state"] = code, state
        return {"access_token": "AT"}
    monkeypatch.setattr(appmod, "_st_exchange_code", fake_exchange)
    r = client.post("/sensor-tower/callback", json={"code": "CODE", "state": "ST"},
                    headers={"authorization": "Bearer t0k"})
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert called == {"code": "CODE", "state": "ST"}

def test_sensor_tower_callback_bad_state_is_400(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, token="t0k")
    import gaa.server.app as appmod
    def fake_exchange(code, state, *, now):
        raise ValueError("unknown or expired state")
    monkeypatch.setattr(appmod, "_st_exchange_code", fake_exchange)
    r = client.post("/sensor-tower/callback", json={"code": "c", "state": "bad"},
                    headers={"authorization": "Bearer t0k"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_app_routes.py -k sensor_tower -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/server/app.py`, add a module-level indirection (for monkeypatching) near the imports:

```python
import time as _time
def _st_exchange_code(code: str, state: str, *, now: float) -> dict:
    from gaa.sensortower import oauth
    return oauth.exchange_code(code, state, now=now)
```

And inside `create_app`, add the route (after `/upload`):

```python
    @app.post("/sensor-tower/callback")
    def sensor_tower_callback(request: Request, body: dict | None = None):
        require_token(request)
        body = body or {}
        code, state = body.get("code"), body.get("state")
        if not code or not state:
            raise HTTPException(status_code=422, detail="code and state required")
        try:
            _st_exchange_code(code, state, now=_time.time())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            _log.exception("sensor tower code exchange failed")
            raise HTTPException(status_code=502, detail="token exchange failed")
        try:
            persist.snapshot(get_ctx())
        except Exception:
            _log.exception("vStorage snapshot after sensor-tower connect failed")
        return JSONResponse({"status": "success"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/server/test_app_routes.py -v`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/app.py tests/server/test_app_routes.py
git commit -m "feat(sensortower): bearer-gated POST /sensor-tower/callback (code exchange)"
```

---

## Task 8: Frontend callback route

**Files:**
- Create: `frontend/app/api/sensor-tower/callback/route.ts`

- [ ] **Step 1: Write the route**

```typescript
// frontend/app/api/sensor-tower/callback/route.ts
import { BACKEND_URL } from "@/lib/gaa/backend";

/** Browser lands here after O365 login. Relay {code,state} to the agent server-to-server,
 *  then render a short page telling the user to return to chat. */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const err = url.searchParams.get("error");

  const page = (title: string, body: string, ok: boolean) =>
    new Response(
      `<!doctype html><meta charset="utf-8"><title>${title}</title>` +
      `<body style="font-family:system-ui;max-width:32rem;margin:4rem auto;text-align:center">` +
      `<h2>${ok ? "✅" : "⚠️"} ${title}</h2><p>${body}</p></body>`,
      { status: ok ? 200 : 400, headers: { "content-type": "text/html; charset=utf-8" } },
    );

  if (err) return page("Sensor Tower connection failed", `O365 returned: ${err}`, false);
  if (!code || !state) return page("Sensor Tower connection failed", "Missing code/state.", false);

  const upstream = await fetch(`${BACKEND_URL()}/sensor-tower/callback`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ code, state }),
  });

  if (!upstream.ok) {
    return page("Sensor Tower connection failed",
      "Couldn't complete the connection. Please try connecting again from the chat.", false);
  }
  return page("Sensor Tower connected",
    "You can close this tab and return to your chat — the agent now has access.", true);
}
```

- [ ] **Step 2: Type-check / build the frontend**

Run: `cd frontend && pnpm tsc --noEmit` (or the repo's lint/build command, e.g. `pnpm lint`)
Expected: no type errors for the new file.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/api/sensor-tower/callback/route.ts
git commit -m "feat(frontend): /api/sensor-tower/callback relays OAuth code to agent"
```

---

## Task 9: Environment & config wiring

**Files:**
- Modify: `Dockerfile` / deploy env (document the two new vars), `frontend` env (`GAA_ST_REDIRECT_URI` is the public Vercel callback)
- Modify: `docs/REBUILD-PRIVATE.md` or the relevant deploy doc (add the new env vars to the runbook)

- [ ] **Step 1: Document + set the agent env vars.**

The agent runtime needs:
- `GAA_ST_BASE_URL` (optional; defaults to staging) — the ST MCP URL.
- `GAA_ST_REDIRECT_URI` (**required**) — the prod Vercel callback, e.g. `https://game-attribution-agent.vercel.app/api/sensor-tower/callback`. Must match the DCR-registered redirect exactly.

Add them to the deploy runbook env list (mirror how `VSTORAGE_*` / `LLM_*` are documented). No code change — these are read by `gaa.sensortower.config`.

- [ ] **Step 2: Confirm the frontend already has `GAA_BACKEND_URL` + `GAA_AGENT_TOKEN`.**

Run: `grep -n "GAA_BACKEND_URL\|GAA_AGENT_TOKEN" frontend/lib/gaa/backend.ts`
Expected: both present (they are). No new frontend env var is required for the relay.

- [ ] **Step 3: Commit (docs only).**

```bash
git add docs/
git commit -m "docs(sensortower): deploy env vars (GAA_ST_BASE_URL, GAA_ST_REDIRECT_URI)"
```

---

## Task 10: Agent operating-rules connect playbook

**Files:**
- Modify: `openclaw/AGENTS.md` — the operating-rules seed the entrypoint copies into the workspace (`scripts/entrypoint.sh` does `cp /opt/gaa/openclaw/AGENTS.md "$WS/AGENTS.md"` only if absent). This is the home for tool-usage playbooks (it already lists the `gaa` analysis tools). Per [[custom-agent-deploy-gotchas]], a persisted (vStorage) workspace copy overrides the seed on an existing instance — so on the live agent the same text must also be applied via the admin `self_edit` path, not just the seed file.

- [ ] **Step 1: Append the playbook** to `openclaw/AGENTS.md`:

```
## Sensor Tower (market data)
You can enrich analysis with live Sensor Tower data. The user must connect their VNG
O365 account once per session.
- Before using Sensor Tower, call `sensor_tower_status`.
- If not connected, call `sensor_tower_connect`, then show the user the returned
  `authorize_url` as a clickable link and ask them to sign in with O365 and come back.
- After they say they're done, call `sensor_tower_status` again to confirm.
- Once connected, use `sensor_tower_list_tools` to see what's available, then
  `sensor_tower_call` with the chosen tool name + arguments.
- Sensor Tower is optional enrichment: if a call returns `not_connected` or
  `upstream_error`, tell the user briefly and continue the analysis without it.
- Never paste tokens or the raw callback URL into chat.
```

- [ ] **Step 2: Apply on the live agent** via the admin self-edit flow (see [[custom-agent-deploy-gotchas]]): the persisted workspace `AGENTS.md` overrides the seed, so updating the seed file alone won't change a running instance.

- [ ] **Step 3: Commit the seed change.**

```bash
git add openclaw/AGENTS.md
git commit -m "feat(sensortower): operating-rules connect→use playbook"
```

---

## Task 11 (optional, gated on Task 0 Step 3): per-tool `st__*` proxying

Only if Task 0 confirmed OpenClaw **re-lists** `gaa` tools mid-conversation. Then `tool_specs()` can append discovered `st__<tool>` entries (cached after first `sensor_tower_list_tools`) with ST's verbatim `inputSchema`, and `run_tool` routes `st__<tool>` → `_st_call_tool(tok, <tool>, args)`. This gives the model native per-tool schemas. Skip if OpenClaw lists once per conversation (the generic passthrough already covers that case). Write tests mirroring Task 6 before implementing.

---

## Task 12: Full suite + live smoke

- [ ] **Step 1: Run the whole Python suite.**

Run: `python -m pytest -q`
Expected: all green (the ~415 existing + the new sensortower/mcp/server tests).

- [ ] **Step 2: Gated live smoke (manual, needs O365 + the deployed agent).**

After deploy (redeploy `gaa-custom-agent` per `/agentbase-deploy`; set `GAA_ST_REDIRECT_URI`; redeploy frontend): in the live chat, ask for market data → agent calls `connect` → log in with O365 → land on the Vercel callback ("connected") → return → agent `sensor_tower_status` connected → `sensor_tower_list_tools` → `sensor_tower_call` returns real ST data. Record the result.

---

## Self-Review notes

- **Spec coverage:** connect tools + proxy (Tasks 6, 8 — generic passthrough per the documented deviation; per-tool deferred to Task 11); token lifecycle/refresh (Task 4); durable storage (Tasks 2–3); security boundaries (Tasks 7–8: bearer-gated server-to-server, no tokens in chat; PKCE/state in Task 4); error handling (`not_connected`/`upstream_error`/`bad_args` in Task 6); Phase-0 spike (Task 0); testing (every Python task is TDD; live smoke Task 12); deploy deltas (Task 9). Phase 1b enrichment + multi-tenancy remain out of scope per the spec.
- **Concurrency caveat** is honored: session defaults to `"default"` (single active session); per-session identity threading is Phase 2.
- **No placeholders:** every code step shows real code; signatures are consistent across tasks (`build_authorize_url(session,*,now)`, `valid_access_token(session,*,now)`, `exchange_code(code,state,*,now)`, `list_tools(token)`, `call_tool(token,name,args)`, store `get/set_tokens`, `pop_pending`, `get/set_client`).
