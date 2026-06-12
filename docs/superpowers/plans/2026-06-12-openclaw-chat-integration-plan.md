# OpenClaw Chat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the live OpenClaw instance (`gaa-chat`) between the React frontend and the GAA runtime so end users chat with OpenClaw, and an admin reconfigures sources/profiles/behavior by chatting.

**Architecture:** Three workstreams in dependency order: (1) GAA grows a SQLite `ConfigStore` + payload-key-guarded admin actions, with sources rebuilt from live config per job; (2) a bootstrap script provisions the OpenClaw workspace (GAA skill, AGENTS.md rules, .env) over the gateway WS protocol; (3) the React app proxies chat to OpenClaw's OpenAI-compatible endpoint and hands `[[gaa:job_id=...]]` markers to the existing GAA poller.

**Tech Stack:** Python 3.9+/pytest/pydantic/sqlite3 (GAA, repo `TestGreenNode`); `websockets` (bootstrap script); React 18 + TypeScript + Vite 6 (repo `gaa-test-frontend`).

**Spec:** `docs/superpowers/specs/2026-06-12-openclaw-chat-integration-design.md` — read it first.

**Two repos:** Tasks 1–7 run in `/Users/lap16006/Documents/Projects/TestGreenNode`. Tasks 8–11 run in `/Users/lap16006/Documents/Projects/gaa-test-frontend` (it is a git repo; commit there). Tasks 12–13 are deployment/E2E checkpoints requiring the user.

**Live facts you can rely on** (verified 2026-06-12, see spec "Spike results"): OpenClaw instance `gaa-chat` = `openclaw-04a7d7f2-2d99-4153-9e4e-00e38c9cc5b5` at `https://openclaw-111723-gaa-chat.agentbase-runtime.aiplatform.vngcloud.vn`; its `/v1/chat/completions` endpoint is already enabled; gateway WS accepts token auth with client id `openclaw-control-ui` + `Origin` header matching the host; workspace edits persist across stop/start. The gateway token is NOT in either repo — ask the user for it when a task needs it (it goes only into `gaa-test-frontend/.env.local` and the bootstrap environment).

---

## Task 1: ConfigStore (GAA)

Runtime-changeable settings with resolution order: stored value → env var → built-in default.

**Files:**
- Create: `src/gaa/store/config_store.py`
- Test: `tests/store/test_config_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/store/test_config_store.py
import pytest

from gaa.store.config_store import ConfigStore, KEYS


@pytest.fixture
def store(tmp_path):
    return ConfigStore(str(tmp_path / "config.sqlite"))


def test_default_when_nothing_set(store, monkeypatch):
    monkeypatch.delenv("GAA_BENCHMARK_MODE", raising=False)
    assert store.resolve("benchmark_mode") == ("snapshot", "default")


def test_env_beats_default(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    assert store.resolve("benchmark_mode") == ("crawl", "env")


def test_empty_env_falls_through_to_default(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "")
    assert store.resolve("benchmark_mode") == ("snapshot", "default")


def test_store_beats_env(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "snapshot")
    store.set("benchmark_mode", "crawl")
    assert store.resolve("benchmark_mode") == ("crawl", "store")


def test_clear_restores_env(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    store.set("benchmark_mode", "snapshot")
    store.set("benchmark_mode", None)
    assert store.resolve("benchmark_mode") == ("crawl", "env")


def test_choices_validated(store):
    with pytest.raises(ValueError):
        store.set("benchmark_mode", "banana")


def test_url_keys_validated(store):
    with pytest.raises(ValueError):
        store.set("signals_url_tmpl", "not-a-url")
    store.set("signals_url_tmpl", "https://example.com/q={q}")
    assert store.resolve("signals_url_tmpl") == ("https://example.com/q={q}", "store")


def test_unknown_key_rejected(store):
    with pytest.raises(KeyError):
        store.set("nope", "x")
    with pytest.raises(KeyError):
        store.resolve("nope")


def test_all_resolved_masks_secrets(store, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    store.set("perplexity_api_key", "pplx-abcdef123456")
    out = store.all_resolved()
    assert set(out) == set(KEYS)
    assert out["perplexity_api_key"]["value"] == "…3456"
    assert out["perplexity_api_key"]["origin"] == "store"


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "config.sqlite")
    ConfigStore(path).set("benchmark_mode", "crawl")
    assert ConfigStore(path).resolve("benchmark_mode") == ("crawl", "store")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/store/test_config_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.store.config_store'`

- [ ] **Step 3: Write the implementation**

```python
# src/gaa/store/config_store.py
"""Runtime-changeable settings with env-var fallback (spec: OpenClaw chat integration).

Resolution order per key: stored value -> environment variable -> built-in default.
Stores live in the same SQLite file as ProfileStore (separate `config` table), so
admin changes survive restarts but env vars still work as deploy-time defaults.
"""
import os
import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ConfigKey:
    name: str
    env: str
    default: str = ""
    secret: bool = False
    choices: Optional[tuple] = None
    is_url: bool = False


KEYS: dict = {k.name: k for k in [
    ConfigKey("benchmark_mode", "GAA_BENCHMARK_MODE",
              default="snapshot", choices=("snapshot", "crawl")),
    ConfigKey("roblox_discover_url_tmpl", "GAA_ROBLOX_DISCOVER_URL_TMPL", is_url=True),
    ConfigKey("roblox_series_url_tmpl", "GAA_ROBLOX_SERIES_URL_TMPL", is_url=True),
    ConfigKey("steam_series_url_tmpl", "GAA_STEAM_SERIES_URL_TMPL", is_url=True),
    ConfigKey("perplexity_api_key", "PERPLEXITY_API_KEY", secret=True),
    ConfigKey("signals_url_tmpl", "GAA_SIGNALS_URL_TMPL", is_url=True),
    ConfigKey("behavior_instructions", "GAA_BEHAVIOR_INSTRUCTIONS"),
]}


class ConfigStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS config "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def resolve(self, name: str) -> tuple:
        """Return (value, origin); origin is 'store' | 'env' | 'default'."""
        key = KEYS[name]  # KeyError on unknown key is intentional
        with self._conn() as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (name,)).fetchone()
        if row is not None:
            return row[0], "store"
        env_val = os.environ.get(key.env, "")
        if env_val:
            return env_val, "env"
        return key.default, "default"

    def set(self, name: str, value: Optional[str]) -> None:
        """Set a stored override; None or '' clears it (falling back to env/default)."""
        key = KEYS.get(name)
        if key is None:
            raise KeyError(f"unknown config key: {name!r} (valid: {sorted(KEYS)})")
        if value is None or str(value).strip() == "":
            with self._conn() as c:
                c.execute("DELETE FROM config WHERE key=?", (name,))
            return
        value = str(value).strip()
        if key.choices and value not in key.choices:
            raise ValueError(f"{name} must be one of {list(key.choices)}, got {value!r}")
        if key.is_url and not value.startswith(("http://", "https://")):
            raise ValueError(f"{name} must start with http:// or https://")
        with self._conn() as c:
            c.execute(
                "INSERT INTO config(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (name, value),
            )

    def all_resolved(self, mask_secrets: bool = True) -> dict:
        out = {}
        for name, key in KEYS.items():
            value, origin = self.resolve(name)
            if mask_secrets and key.secret and value:
                value = "…" + value[-4:]
            out[name] = {"value": value, "origin": origin}
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/store/test_config_store.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/gaa/store/config_store.py tests/store/test_config_store.py
git commit -m "feat: ConfigStore — runtime settings with store→env→default resolution"
```

---

## Task 2: AdminActions (GAA)

Admin actions guarded by a payload `admin_key` (payload-based because the AgentBase SDK does not guarantee arbitrary header passthrough).

**Files:**
- Create: `src/gaa/admin_actions.py`
- Test: `tests/test_admin_actions.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_actions.py
import pytest

from gaa.admin_actions import AdminActions, ADMIN_ACTIONS, MAX_BEHAVIOR_CHARS
from gaa.schema.profile import ColumnMapping, GameProfile
from gaa.store.config_store import ConfigStore
from gaa.store.profile_store import ProfileStore


def make_profile(name: str) -> GameProfile:
    return GameProfile(
        name=name, platform="Custom", genre="survival",
        mapping=ColumnMapping(date_col="date", metric_cols={"rev": "revenue"}),
    )


@pytest.fixture
def admin(tmp_path):
    config = ConfigStore(str(tmp_path / "db.sqlite"))
    profiles = ProfileStore(str(tmp_path / "db.sqlite"))
    return AdminActions(config=config, profiles=profiles, admin_key="sekret"), config, profiles


def test_disabled_without_key(tmp_path):
    a = AdminActions(
        config=ConfigStore(str(tmp_path / "x.sqlite")),
        profiles=ProfileStore(str(tmp_path / "x.sqlite")),
        admin_key="",
    )
    out = a.handle("admin_get_config", {"admin_key": "anything"})
    assert out["status"] == "error" and "disabled" in out["error"]


def test_wrong_key_rejected(admin):
    a, _, _ = admin
    out = a.handle("admin_get_config", {"admin_key": "wrong"})
    assert out == {"status": "error", "code": 403, "error": "not authorized"}


def test_get_config(admin):
    a, _, _ = admin
    out = a.handle("admin_get_config", {"admin_key": "sekret"})
    assert out["status"] == "success"
    assert out["config"]["benchmark_mode"]["value"] == "snapshot"


def test_set_config_roundtrip(admin):
    a, config, _ = admin
    out = a.handle("admin_set_config",
                   {"admin_key": "sekret", "config": {"benchmark_mode": "crawl"}})
    assert out["status"] == "success"
    assert config.resolve("benchmark_mode") == ("crawl", "store")
    assert out["config"]["benchmark_mode"]["value"] == "crawl"


def test_set_config_validates(admin):
    a, _, _ = admin
    out = a.handle("admin_set_config",
                   {"admin_key": "sekret", "config": {"benchmark_mode": "banana"}})
    assert out["status"] == "error" and "benchmark_mode" in out["error"]
    out = a.handle("admin_set_config", {"admin_key": "sekret", "config": {}})
    assert out["status"] == "error"


def test_set_behavior_and_cap(admin):
    a, config, _ = admin
    out = a.handle("admin_set_behavior",
                   {"admin_key": "sekret", "instructions": "Answer in Vietnamese."})
    assert out["status"] == "success"
    assert config.resolve("behavior_instructions")[0] == "Answer in Vietnamese."
    out = a.handle("admin_set_behavior",
                   {"admin_key": "sekret", "instructions": "x" * (MAX_BEHAVIOR_CHARS + 1)})
    assert out["status"] == "error" and "too long" in out["error"]


def test_profiles_list_and_activate(admin):
    a, _, profiles = admin
    profiles.save(make_profile("alpha"))
    profiles.save(make_profile("beta"))
    profiles.set_active("alpha")

    out = a.handle("list_profiles", {"admin_key": "sekret"})
    assert out["profiles"] == ["alpha", "beta"] and out["active"] == "alpha"

    out = a.handle("set_active_profile", {"admin_key": "sekret", "name": "beta"})
    assert out["status"] == "success" and out["active"] == "beta"
    assert profiles.get_active().name == "beta"

    out = a.handle("set_active_profile", {"admin_key": "sekret", "name": "ghost"})
    assert out["status"] == "error"


def test_action_set_is_complete():
    assert ADMIN_ACTIONS == {"admin_get_config", "admin_set_config",
                             "admin_set_behavior", "list_profiles",
                             "set_active_profile"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_actions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.admin_actions'`

- [ ] **Step 3: Write the implementation**

```python
# src/gaa/admin_actions.py
"""Admin actions on /invocations, guarded by a payload `admin_key`.

The key travels in the payload (not a header) because the AgentBase SDK does not
guarantee arbitrary header passthrough to the handler. Comparison is constant-time.
With GAA_ADMIN_KEY unset, every admin action is refused.

Note: admin_set_config applies keys in order and stops at the first invalid one —
earlier keys in the same request stay applied. The response always returns the
full resolved config, so the caller sees the actual state either way.
"""
import hmac
import os
from typing import Optional

from gaa.store.config_store import ConfigStore
from gaa.store.profile_store import ProfileStore

ADMIN_ACTIONS = {
    "admin_get_config",
    "admin_set_config",
    "admin_set_behavior",
    "list_profiles",
    "set_active_profile",
}

MAX_BEHAVIOR_CHARS = 2000


class AdminActions:
    def __init__(self, config: ConfigStore, profiles: ProfileStore,
                 admin_key: Optional[str] = None) -> None:
        self._config = config
        self._profiles = profiles
        self._admin_key = (admin_key if admin_key is not None
                           else os.environ.get("GAA_ADMIN_KEY", ""))

    def handle(self, action: str, payload: dict) -> dict:
        if not self._admin_key:
            return {"status": "error", "code": 403,
                    "error": "admin actions disabled (GAA_ADMIN_KEY not set)"}
        if not hmac.compare_digest(str(payload.get("admin_key", "")), self._admin_key):
            return {"status": "error", "code": 403, "error": "not authorized"}
        try:
            return getattr(self, f"_{action}")(payload)
        except (KeyError, ValueError) as exc:
            return {"status": "error", "error": str(exc)}

    def _admin_get_config(self, payload: dict) -> dict:
        return {"status": "success", "mode": "admin",
                "config": self._config.all_resolved()}

    def _admin_set_config(self, payload: dict) -> dict:
        changes = payload.get("config")
        if not isinstance(changes, dict) or not changes:
            return {"status": "error",
                    "error": "payload must include a non-empty `config` object"}
        for name, value in changes.items():
            self._config.set(name, value)
        return {"status": "success", "mode": "admin",
                "config": self._config.all_resolved()}

    def _admin_set_behavior(self, payload: dict) -> dict:
        text = str(payload.get("instructions", "")).strip()
        if len(text) > MAX_BEHAVIOR_CHARS:
            return {"status": "error",
                    "error": f"instructions too long ({len(text)} > {MAX_BEHAVIOR_CHARS} chars)"}
        self._config.set("behavior_instructions", text or None)
        return {"status": "success", "mode": "admin", "behavior_instructions": text}

    def _list_profiles(self, payload: dict) -> dict:
        active = self._profiles.get_active()
        return {"status": "success", "mode": "admin",
                "profiles": self._profiles.list_names(),
                "active": active.name if active else None}

    def _set_active_profile(self, payload: dict) -> dict:
        name = str(payload.get("name", ""))
        if name not in self._profiles.list_names():
            return {"status": "error", "error": f"unknown profile: {name!r}"}
        self._profiles.set_active(name)
        return {"status": "success", "mode": "admin", "active": name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_admin_actions.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/gaa/admin_actions.py tests/test_admin_actions.py
git commit -m "feat: admin actions — config/behavior/profile ops guarded by payload admin_key"
```

---

## Task 3: Route admin actions through GraphAgent (GAA)

**Files:**
- Modify: `src/gaa/graph.py` (imports at top; routing inside `handle()` at the current `action = payload.get("action")` block, around line 89–97)
- Test: `tests/test_graph_admin.py` (new file — keeps `tests/test_graph.py` untouched)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_admin.py
from gaa.graph import GraphAgent


class StubAdmin:
    def __init__(self):
        self.calls = []

    def handle(self, action, payload):
        self.calls.append((action, payload))
        return {"status": "success", "mode": "admin", "echo": action}


def make_agent(admin=None):
    # GraphAgent only touches jobs/pipeline/profiles/etc. on non-admin paths,
    # so None placeholders are fine for this routing test.
    return GraphAgent(jobs=None, pipeline=None, profile_store=None,
                      metrics_store=None, benchmark=None, profiler=None,
                      admin=admin)


def test_admin_action_routed_to_admin_handler():
    admin = StubAdmin()
    agent = make_agent(admin)
    out = agent.handle({"action": "admin_get_config", "admin_key": "k"}, "s1", "u1")
    assert out == {"status": "success", "mode": "admin", "echo": "admin_get_config"}
    assert admin.calls[0][0] == "admin_get_config"


def test_admin_action_without_admin_configured():
    agent = make_agent(admin=None)
    out = agent.handle({"action": "admin_get_config", "admin_key": "k"}, "s1", "u1")
    assert out["status"] == "error" and "not configured" in out["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph_admin.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'admin'`

- [ ] **Step 3: Implement the routing**

In `src/gaa/graph.py`, add the import after the existing imports (line 14):

```python
from gaa.admin_actions import ADMIN_ACTIONS
```

Add the `admin` parameter to `GraphAgent.__init__` (after `request_budget_s`, before the legacy params) and store it:

```python
        request_budget_s: float = 40.0,
        admin=None,
        # Legacy params kept for backward compat (engine, checkpointer ignored)
        engine=None,
        checkpointer=None,
    ) -> None:
```

and in the body, with the other assignments:

```python
        self._admin = admin
```

In `handle()`, insert immediately after `action = payload.get("action")`:

```python
        if action in ADMIN_ACTIONS:
            if self._admin is None:
                return {"status": "error", "error": "admin actions not configured"}
            return self._admin.handle(action, payload)
```

- [ ] **Step 4: Run tests — new file and the existing graph suites**

Run: `python -m pytest tests/test_graph_admin.py tests/test_graph.py tests/test_graph_onboarding.py -v`
Expected: all pass (existing tests construct GraphAgent without `admin`, which defaults to None)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/graph.py tests/test_graph_admin.py
git commit -m "feat: route admin_* actions through GraphAgent to AdminActions"
```

---

## Task 4: Dynamic sources — config honored per job (GAA)

Facades that rebuild the provider stack from current ConfigStore values on every call, so admin changes apply without restart and without touching `AnalysisPipeline`.

**Files:**
- Create: `src/gaa/sources/dynamic.py`
- Test: `tests/sources/test_dynamic.py`

Reference signatures (already verified): `BenchmarkRefresher.refresh(self, platform, genre, start=None, end=None, deadline=None) -> dict` (`src/gaa/crawl/refresher.py:46`); `SignalsSource.events(self, game, genre, start, end) -> list[dict]` (`src/gaa/sources/base.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/sources/test_dynamic.py
import pytest

import gaa.sources.dynamic as dyn
from gaa.config import Settings
from gaa.store.config_store import ConfigStore


class StubRefresher:
    last_kwargs = None

    def __init__(self, store, providers_by_platform, web_provider):
        StubRefresher.last_kwargs = {
            "store": store,
            "providers_by_platform": providers_by_platform,
            "web_provider": web_provider,
        }

    def refresh(self, platform, genre, start=None, end=None, deadline=None):
        return {"status": "ok", "platform": platform}


class StubSignals:
    def __init__(self, *a, **kw):
        self.kw = kw

    def events(self, game, genre, start, end):
        return [{"src": "web"}]


class StubFixture:
    def __init__(self, items):
        self.items = items

    def events(self, game, genre, start, end):
        return []


@pytest.fixture
def config(tmp_path, monkeypatch):
    for var in ("GAA_BENCHMARK_MODE", "GAA_ROBLOX_DISCOVER_URL_TMPL",
                "GAA_ROBLOX_SERIES_URL_TMPL", "GAA_STEAM_SERIES_URL_TMPL",
                "PERPLEXITY_API_KEY", "GAA_SIGNALS_URL_TMPL"):
        monkeypatch.delenv(var, raising=False)
    return ConfigStore(str(tmp_path / "c.sqlite"))


@pytest.fixture
def settings(tmp_path):
    return Settings(cache_dir=str(tmp_path / "cache"))


def test_snapshot_mode_builds_empty_providers(config, settings, monkeypatch):
    monkeypatch.setattr(dyn, "BenchmarkRefresher", StubRefresher)
    r = dyn.DynamicRefresher(config=config, settings=settings, store="STORE")
    out = r.refresh("roblox", "survival", "2026-01-01", "2026-01-31")
    assert out["status"] == "ok"
    assert StubRefresher.last_kwargs["providers_by_platform"] == {}
    assert StubRefresher.last_kwargs["web_provider"] is None


def test_crawl_mode_builds_providers_from_current_config(config, settings, monkeypatch):
    monkeypatch.setattr(dyn, "BenchmarkRefresher", StubRefresher)
    r = dyn.DynamicRefresher(config=config, settings=settings, store="STORE")
    # flip config AFTER constructing the facade — must take effect on next call
    config.set("benchmark_mode", "crawl")
    config.set("perplexity_api_key", "pplx-test")
    r.refresh("steam", "survival")
    kw = StubRefresher.last_kwargs
    assert set(kw["providers_by_platform"]) == {"roblox", "steam"}
    assert kw["web_provider"] is not None


def test_dynamic_signals_switches_on_config(config, settings, monkeypatch):
    monkeypatch.setattr(dyn, "WebSignalsSource", StubSignals)
    monkeypatch.setattr(dyn, "FixtureSignalsSource", StubFixture)
    s = dyn.DynamicSignals(config=config, settings=settings)
    assert s.events("g", "survival", "2026-01-01", "2026-01-31") == []
    config.set("signals_url_tmpl", "https://example.com/news?q={q}")
    assert s.events("g", "survival", "2026-01-01", "2026-01-31") == [{"src": "web"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/sources/test_dynamic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.sources.dynamic'`

- [ ] **Step 3: Write the implementation**

```python
# src/gaa/sources/dynamic.py
"""Config-driven source facades.

These rebuild their underlying provider stack from the current ConfigStore values
on every call, so admin config changes take effect on the next job without a
process restart — and AnalysisPipeline keeps its existing refresher/signals API.
"""
import dataclasses
import os

from gaa.config import Settings
from gaa.crawl.fetcher import CachedFetcher
from gaa.crawl.perplexity import perplexity_answer
from gaa.crawl.refresher import BenchmarkRefresher
from gaa.sources.fixtures import FixtureSignalsSource
from gaa.sources.providers.roblox import RobloxBenchmarkProvider
from gaa.sources.providers.steam import SteamBenchmarkProvider
from gaa.sources.providers.web import WebSearchBenchmarkProvider
from gaa.sources.web_signals import WebSignalsSource
from gaa.store.config_store import ConfigStore


class DynamicRefresher:
    """BenchmarkRefresher facade that honors the live ConfigStore on each refresh."""

    def __init__(self, config: ConfigStore, settings: Settings, store) -> None:
        self._config = config
        self._settings = settings
        self._store = store

    def _cfg(self, name: str) -> str:
        return self._config.resolve(name)[0]

    def _build(self) -> BenchmarkRefresher:
        if self._cfg("benchmark_mode") != "crawl":
            return BenchmarkRefresher(store=self._store,
                                      providers_by_platform={}, web_provider=None)
        cache = self._settings.cache_dir + "/benchmark"
        providers = {
            "roblox": [RobloxBenchmarkProvider(
                fetcher=CachedFetcher(cache),
                discover_url_tmpl=self._cfg("roblox_discover_url_tmpl"),
                series_url_tmpl=self._cfg("roblox_series_url_tmpl"),
            )],
            "steam": [SteamBenchmarkProvider(
                fetcher=CachedFetcher(cache),
                # genre→appid map is built into the provider; discover stays env-only
                discover_url_tmpl=os.environ.get("GAA_STEAM_DISCOVER_URL_TMPL", ""),
                series_url_tmpl=self._cfg("steam_series_url_tmpl"),
            )],
        }
        pkey = self._cfg("perplexity_api_key")
        web = None
        if pkey:
            psettings = dataclasses.replace(self._settings, perplexity_api_key=pkey)
            web = WebSearchBenchmarkProvider(
                lambda prompt: perplexity_answer(prompt, psettings))
        return BenchmarkRefresher(store=self._store,
                                  providers_by_platform=providers, web_provider=web)

    def refresh(self, platform, genre, start=None, end=None, deadline=None) -> dict:
        return self._build().refresh(platform, genre, start, end, deadline=deadline)


class DynamicSignals:
    """SignalsSource facade that honors the live ConfigStore on each call."""

    def __init__(self, config: ConfigStore, settings: Settings) -> None:
        self._config = config
        self._settings = settings

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        tmpl = self._config.resolve("signals_url_tmpl")[0]
        src = (WebSignalsSource(cache_dir=self._settings.cache_dir + "/signals",
                                query_url_tmpl=tmpl)
               if tmpl else FixtureSignalsSource([]))
        return src.events(game, genre, start, end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/sources/test_dynamic.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sources/dynamic.py tests/sources/test_dynamic.py
git commit -m "feat: dynamic benchmark/signals facades rebuilt from live config per job"
```

---

## Task 5: Synthesizer operator preferences (GAA)

**Files:**
- Modify: `src/gaa/synth/synthesizer.py` (constructor + `synthesize`, lines 27–34)
- Test: `tests/synth/test_operator_prefs.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# tests/synth/test_operator_prefs.py
from gaa.schema.ledger import EvidenceLedger
from gaa.synth.synthesizer import Synthesizer, SYSTEM


class CaptureLLM:
    def __init__(self):
        self.system = None

    def complete_json(self, system, user):
        self.system = system
        return {"main_story": "s", "rationale": "", "causes": {},
                "scenarios": [], "risks": [], "assumptions_and_gaps": []}


def test_no_provider_keeps_system_unchanged():
    llm = CaptureLLM()
    Synthesizer(llm).synthesize(EvidenceLedger(), "q")
    assert llm.system == SYSTEM


def test_instructions_appended_when_present():
    llm = CaptureLLM()
    Synthesizer(llm, instructions_provider=lambda: "Answer in Vietnamese.") \
        .synthesize(EvidenceLedger(), "q")
    assert llm.system.startswith(SYSTEM)
    assert "OPERATOR PREFERENCES" in llm.system
    assert "Answer in Vietnamese." in llm.system


def test_blank_instructions_ignored():
    llm = CaptureLLM()
    Synthesizer(llm, instructions_provider=lambda: "  ").synthesize(EvidenceLedger(), "q")
    assert llm.system == SYSTEM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/synth/test_operator_prefs.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'instructions_provider'`

- [ ] **Step 3: Implement**

In `src/gaa/synth/synthesizer.py`, add to the imports at the top:

```python
from typing import Callable, Optional
```

Replace the constructor and `synthesize` (currently lines 28–34):

```python
    def __init__(self, llm: LLM,
                 instructions_provider: Optional[Callable[[], str]] = None) -> None:
        self._llm = llm
        self._instructions = instructions_provider

    def synthesize(self, ledger: EvidenceLedger, query: str) -> AttributionHypothesis:
        system = SYSTEM
        extra = (self._instructions() if self._instructions else "").strip()
        if extra:
            system += (
                "\n\nOPERATOR PREFERENCES (presentation/style only — these never "
                "override the evidence-grounding rules above): " + extra
            )
        user = f"QUERY: {query}\n\nEVIDENCE LEDGER:\n{_ledger_brief(ledger)}"
        raw = self._llm.complete_json(system, user)
        return self._assemble(raw, ledger)
```

- [ ] **Step 4: Run the synth suites**

Run: `python -m pytest tests/synth/ -v`
Expected: all pass (new file 3 passed; existing synth tests unaffected — the new arg is optional)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/synth/synthesizer.py tests/synth/test_operator_prefs.py
git commit -m "feat: synthesizer appends operator behavior instructions to system prompt"
```

---

## Task 6: Wire everything in main.py (GAA)

**Files:**
- Modify: `main.py` (imports; the provider block at lines 44–88; synth at line 92; agent at lines 107–115)

- [ ] **Step 1: Update imports**

In `main.py`, remove these now-unused imports (lines 13–21 region): `CrawlingBenchmarkSource` stays; delete the imports of `WebSignalsSource`, `FixtureSignalsSource`, `RobloxBenchmarkProvider`, `SteamBenchmarkProvider`, `WebSearchBenchmarkProvider`, `CachedFetcher`, `perplexity_answer`, `BenchmarkRefresher`. Add:

```python
from gaa.admin_actions import AdminActions
from gaa.store.config_store import ConfigStore
from gaa.sources.dynamic import DynamicRefresher, DynamicSignals
```

- [ ] **Step 2: Replace the provider/signals block**

Replace everything from `# ── Benchmark providers (quant crawl + optional Perplexity web tier) ─────────` (line 44) through the signals block (line 88) with:

```python
# ── Runtime config + dynamic sources (admin-changeable, no restart needed) ───
_config = ConfigStore(settings.db_path)
_refresher = DynamicRefresher(config=_config, settings=settings, store=_benchmark_store)
_signals = DynamicSignals(config=_config, settings=settings)
```

- [ ] **Step 3: Wire synthesizer + admin into the agent**

Replace `_synth = Synthesizer(_llm)` (line 92) with:

```python
_synth = Synthesizer(
    _llm,
    instructions_provider=lambda: _config.resolve("behavior_instructions")[0],
)
```

Replace the `_agent = GraphAgent(...)` call (lines 107–115) with:

```python
_admin = AdminActions(config=_config, profiles=_profile_store)

_agent = GraphAgent(
    jobs=_jobs,
    pipeline=_pipeline,
    profile_store=_profile_store,
    metrics_store=_metrics_store,
    benchmark=_benchmark,
    profiler=Profiler(_llm),
    request_budget_s=float(os.environ.get("GAA_REQUEST_BUDGET_S", "40")),
    admin=_admin,
)
```

- [ ] **Step 4: Verify — syntax + full test suite**

Run: `python -c "import ast; ast.parse(open('main.py').read()); print('main.py OK')" && python -m pytest -q`
Expected: `main.py OK` and the full suite passes (was 177 tests before this feature; now 177 + the ~24 added in Tasks 1–5)

- [ ] **Step 5: Local smoke test of an admin action**

```bash
GAA_ADMIN_KEY=localtest python main.py &
sleep 3
curl -s -X POST http://localhost:8080/invocations -H 'content-type: application/json' \
  -d '{"action":"admin_get_config","admin_key":"localtest"}'
kill %1
```

Expected: JSON with `"status": "success"` and a `config` object showing `benchmark_mode` with origin `default` (or `env` if your shell exports `GAA_BENCHMARK_MODE`). Note: the SDK may wrap the path differently locally — if `/invocations` 404s, retry with the path printed in the server log.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: wire ConfigStore, dynamic sources, operator prefs, admin actions into app"
```

---

## Task 7: OpenClaw bootstrap script (GAA repo)

Idempotent provisioning of the `gaa-chat` workspace over the gateway WS protocol. Requires the `websockets` package (`pip install "websockets>=11"` — dev/ops dependency only; do NOT add it to `requirements.txt`, the runtime image doesn't need it).

**Files:**
- Create: `scripts/openclaw_bootstrap.py`

**Secrets handling:** the script reads `OPENCLAW_URL`, `OPENCLAW_TOKEN`, `GAA_ENDPOINT`, `GAA_ADMIN_KEY` from its environment. Ask the user to export them (the OpenClaw token was captured at instance create; the admin key is generated in Task 12). Never commit or print them.

- [ ] **Step 1: Write the script**

```python
# scripts/openclaw_bootstrap.py
"""Provision the gaa-chat OpenClaw workspace for the GAA integration.

Idempotent: safe to re-run any time (e.g. after a platform version switch).
  1. Enables gateway.http.endpoints.chatCompletions in openclaw.json (config.set).
  2. Writes the GAA skill, workspace .env, and AGENTS.md addendum (agents.files.set).
  3. Verifies: HTTP chat endpoint answers; workspace files present.

Env vars (all required):
  OPENCLAW_URL    e.g. https://openclaw-111723-gaa-chat.agentbase-runtime.aiplatform.vngcloud.vn
  OPENCLAW_TOKEN  gateway token (issued once at instance create)
  GAA_ENDPOINT    e.g. https://endpoint-f6f69523-....agentbase-runtime.aiplatform.vngcloud.vn
  GAA_ADMIN_KEY   the admin key set on the GAA runtime

Usage: python scripts/openclaw_bootstrap.py
"""
import asyncio
import json
import os
import sys
import urllib.request
import uuid

import websockets

OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "").rstrip("/")
TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
GAA_ENDPOINT = os.environ.get("GAA_ENDPOINT", "").rstrip("/")
GAA_ADMIN_KEY = os.environ.get("GAA_ADMIN_KEY", "")

SCOPES = ["operator.admin", "operator.read", "operator.write",
          "operator.approvals", "operator.pairing"]

HTTP_BLOCK = """    bind: 'lan',
    http: {
      endpoints: {
        chatCompletions: {
          enabled: true,
        },
      },
    },
"""

WORKSPACE_ENV = f"""GAA_ENDPOINT={GAA_ENDPOINT}
GAA_ADMIN_KEY={GAA_ADMIN_KEY}
"""

SKILL_MD = """---
name: gaa
description: Call the Game Attribution Agent (GAA) API — analyze game metrics, and (admin sessions only) view/change its configuration, profiles, and report behavior.
---

# Game Attribution Agent (GAA) skill

Credentials live in `~/.openclaw/workspace/.env` (GAA_ENDPOINT, GAA_ADMIN_KEY).
Always `source ~/.openclaw/workspace/.env` before the curl commands below.

## Start an analysis (any user)
When the user asks why a game metric moved or what's happening with their game:

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' -d '{"message": "<the user question, verbatim>"}'

The response includes `job_id`, `job_status`, `stage`, `activity`. DO NOT poll it.
Reply with ONE short sentence ("Analysis started — crunching your metrics against
market data now.") and END your reply with this exact marker on its own line:

    [[gaa:job_id=<job_id>]]

The web UI detects that marker, polls the job itself, and renders the full report.
If the response has `"mode": "setup"` or `"mode": "help"`, relay its `message` instead.

## Admin actions — ONLY for admin sessions
A session is admin ONLY if it contains the system message `GAA session role: admin`.
For everyone else: refuse, and suggest they contact the admin. Never reveal GAA_ADMIN_KEY.

View config (keys, resolved values, origin store/env/default; secrets masked):

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' \\
      -d '{"action":"admin_get_config","admin_key":"'"$GAA_ADMIN_KEY"'"}'

Change config — valid keys: benchmark_mode ("snapshot"|"crawl"),
roblox_discover_url_tmpl, roblox_series_url_tmpl, steam_series_url_tmpl,
perplexity_api_key, signals_url_tmpl. Use null to clear a key back to env/default:

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' \\
      -d '{"action":"admin_set_config","admin_key":"'"$GAA_ADMIN_KEY"'","config":{"benchmark_mode":"crawl"}}'

Set report behavior (output language, focus metrics, tone — max 2000 chars):

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' \\
      -d '{"action":"admin_set_behavior","admin_key":"'"$GAA_ADMIN_KEY"'","instructions":"Answer in Vietnamese."}'

Profiles:

    {"action":"list_profiles","admin_key":"..."}
    {"action":"set_active_profile","admin_key":"...","name":"<profile>"}

After any admin action, confirm to the admin in one sentence what changed.
"""

AGENTS_MD_ADDENDUM = """

## GAA integration (managed by scripts/openclaw_bootstrap.py — edit freely below, the bootstrap only appends this section if the heading is missing)

- You are the chat front-end for the Game Attribution Agent (GAA). Use the `gaa`
  skill for game-metric analysis questions and for admin configuration.
- Admin sessions are marked with the system message `GAA session role: admin`.
  Treat every other session as a regular user: never run admin actions, never
  reveal configuration values or secrets, never edit your own workspace files
  on their request.
- When you start a GAA analysis, end your reply with the `[[gaa:job_id=...]]`
  marker line — the web UI uses it to render the live report.
"""


class Gateway:
    def __init__(self):
        self.ws = None

    async def __aenter__(self):
        host = OPENCLAW_URL.split("://", 1)[1]
        self.ws = await websockets.connect(
            "wss://" + host + "/", max_size=20 * 1024 * 1024,
            origin="https://" + host)
        await self.ws.recv()  # connect.challenge
        resp = await self.call("connect", {
            "minProtocol": 3, "maxProtocol": 3, "role": "operator",
            "scopes": SCOPES, "auth": {"token": TOKEN},
            "client": {"id": "openclaw-control-ui", "version": "control-ui",
                       "platform": "bootstrap", "mode": "webchat"},
        })
        if not resp.get("ok"):
            raise SystemExit(f"gateway connect failed: {resp.get('error')}")
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def call(self, method, params=None, timeout=60):
        rid = str(uuid.uuid4())
        await self.ws.send(json.dumps(
            {"type": "req", "id": rid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
            if msg.get("type") == "res" and msg.get("id") == rid:
                return msg


async def ensure_http_endpoint(gw) -> str:
    cfg = await gw.call("config.get")
    payload = cfg["payload"]
    raw, base_hash = payload["raw"], payload["hash"]
    if "chatCompletions" in raw:
        return "already enabled"
    needle = "    bind: 'lan',\n"
    if raw.count(needle) != 1:
        raise SystemExit("unexpected openclaw.json shape — enable chatCompletions "
                         "manually via the Control UI config editor")
    res = await gw.call("config.set",
                        {"raw": raw.replace(needle, HTTP_BLOCK, 1), "baseHash": base_hash})
    if not res.get("ok"):
        raise SystemExit(f"config.set failed: {res.get('error')}")
    return "enabled"


async def write_file(gw, name: str, content: str) -> str:
    res = await gw.call("agents.files.set",
                        {"agentId": "main", "name": name, "content": content})
    if not res.get("ok"):
        return f"FAILED ({(res.get('error') or {}).get('message')})"
    back = await gw.call("agents.files.get", {"agentId": "main", "name": name})
    ok = back.get("ok") and back["payload"]["file"]["content"] == content
    return "written" if ok else "VERIFY FAILED"


async def append_agents_md(gw) -> str:
    cur = await gw.call("agents.files.get", {"agentId": "main", "name": "AGENTS.md"})
    content = cur["payload"]["file"]["content"] if cur.get("ok") else ""
    if "## GAA integration" in content:
        return "already present"
    return await write_file(gw, "AGENTS.md", content + AGENTS_MD_ADDENDUM)


def probe_http() -> str:
    req = urllib.request.Request(
        OPENCLAW_URL + "/v1/chat/completions",
        data=json.dumps({"model": "openclaw", "user": "bootstrap-probe",
                         "messages": [{"role": "user",
                                       "content": "Reply with exactly: PONG"}]}).encode(),
        headers={"authorization": "Bearer " + TOKEN,
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"][:40]


async def main():
    missing = [k for k, v in [("OPENCLAW_URL", OPENCLAW_URL), ("OPENCLAW_TOKEN", TOKEN),
                              ("GAA_ENDPOINT", GAA_ENDPOINT), ("GAA_ADMIN_KEY", GAA_ADMIN_KEY)]
               if not v]
    if missing:
        sys.exit(f"missing env vars: {', '.join(missing)}")

    async with Gateway() as gw:
        print("[1/4] chatCompletions endpoint:", await ensure_http_endpoint(gw))
        print("[2/4] skills/gaa/SKILL.md:", await write_file(gw, "skills/gaa/SKILL.md", SKILL_MD))
        print("      .env:", await write_file(gw, ".env", WORKSPACE_ENV))
        print("[3/4] AGENTS.md addendum:", await append_agents_md(gw))
    print("[4/4] HTTP chat probe:", probe_http())
    print("Bootstrap complete.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Syntax check**

Run: `python -c "import ast; ast.parse(open('scripts/openclaw_bootstrap.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Live run against gaa-chat (needs secrets from the user)**

Ask the user to run (filling in the two secrets — do not echo them into the transcript):

```bash
pip install "websockets>=11"
export OPENCLAW_URL=https://openclaw-111723-gaa-chat.agentbase-runtime.aiplatform.vngcloud.vn
export OPENCLAW_TOKEN=<gateway token>
export GAA_ENDPOINT=https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn
export GAA_ADMIN_KEY=<key from Task 12 — use a placeholder value for now if Task 12 hasn't run; re-run bootstrap after>
python scripts/openclaw_bootstrap.py
```

Expected output: all four steps report `enabled`/`already enabled`/`written`/`already present`, and the probe prints `PONG`.

**Known risk:** `agents.files.set` was not exercised in the spike (only `files.get`/`files.list`). If it rejects nested names like `skills/gaa/SKILL.md`, fall back to asking the agent to write the files itself: open the Control UI (`OPENCLAW_URL` + `#token=...`) and paste: *"Create the file `skills/gaa/SKILL.md` in your workspace with exactly the following content, then confirm: …"* — then re-run the bootstrap to verify (it re-reads files and reports `already present`/`written`).

- [ ] **Step 4: Commit**

```bash
git add scripts/openclaw_bootstrap.py
git commit -m "feat: idempotent OpenClaw workspace bootstrap (endpoint, GAA skill, AGENTS.md)"
```

---

## Task 8: Frontend — OpenClaw proxy route (gaa-test-frontend)

Work in `/Users/lap16006/Documents/Projects/gaa-test-frontend` from here through Task 11.

**Files:**
- Modify: `vite.config.ts`
- Create: `.env.local` (user supplies the token; file is already git-ignored via `.env.local` and `*.local`)

- [ ] **Step 1: Add the proxy plugin and env loading**

In `vite.config.ts`: change the first import line and the export. Add this plugin function after the existing `agentProxy()` function:

```ts
/**
 * Same-origin proxy for the OpenClaw chat endpoint. The gateway token grants FULL
 * operator access, so it must never reach the browser: it lives in .env.local and
 * is injected here, server-side. Streams the body through (SSE-compatible).
 */
function openclawProxy(env: Record<string, string>): Plugin {
  return {
    name: 'gaa-openclaw-proxy',
    configureServer(server) {
      server.middlewares.use('/openclaw', async (req, res) => {
        const base = (env.OPENCLAW_URL || '').replace(/\/+$/, '')
        const token = env.OPENCLAW_TOKEN || ''
        if (!base || !token) {
          res.statusCode = 500
          res.setHeader('content-type', 'application/json')
          res.end(JSON.stringify({ error: 'Set OPENCLAW_URL and OPENCLAW_TOKEN in .env.local, then restart vite.' }))
          return
        }
        const target = base + (req.url || '/')

        const method = (req.method || 'GET').toUpperCase()
        let body: Buffer | undefined
        if (method !== 'GET' && method !== 'HEAD') {
          const chunks: Buffer[] = []
          for await (const c of req) chunks.push(c as Buffer)
          body = chunks.length ? Buffer.concat(chunks) : undefined
        }

        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 300_000)
        try {
          const upstream = await fetch(target, {
            method,
            headers: {
              authorization: `Bearer ${token}`,
              'content-type': (req.headers['content-type'] as string) || 'application/json',
              accept: (req.headers['accept'] as string) || '*/*',
            },
            body,
            signal: controller.signal,
          })
          res.statusCode = upstream.status
          res.setHeader('content-type', upstream.headers.get('content-type') || 'application/json')
          if (upstream.body) {
            // Stream chunks through so SSE deltas reach the browser as they arrive.
            const reader = upstream.body.getReader()
            for (;;) {
              const { done, value } = await reader.read()
              if (done) break
              res.write(Buffer.from(value))
            }
          }
          res.end()
        } catch (err) {
          const aborted = (err as Error)?.name === 'AbortError'
          res.statusCode = aborted ? 504 : 502
          res.setHeader('content-type', 'application/json')
          res.end(JSON.stringify({
            error: aborted ? `OpenClaw timed out after 300s` : `Proxy could not reach OpenClaw: ${(err as Error)?.message ?? err}`,
          }))
        } finally {
          clearTimeout(timeout)
        }
      })
    },
  }
}
```

Replace the bottom `export default defineConfig({...})` with:

```ts
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), agentProxy(), openclawProxy(env)],
    server: { port: 5173 },
  }
})
```

and change the top import to include `loadEnv`:

```ts
import { defineConfig, loadEnv, type Plugin } from 'vite'
```

- [ ] **Step 2: Create `.env.local` (user supplies the token)**

Ask the user to create `/Users/lap16006/Documents/Projects/gaa-test-frontend/.env.local` themselves (it holds a secret — don't write the token into the transcript):

```
OPENCLAW_URL=https://openclaw-111723-gaa-chat.agentbase-runtime.aiplatform.vngcloud.vn
OPENCLAW_TOKEN=<gateway token from the create response>
```

- [ ] **Step 3: Verify — typecheck + live probe through the proxy**

Run: `npm run typecheck`
Expected: no errors.

Run: `npm run dev` in the background, then:

```bash
curl -s -X POST http://localhost:5173/openclaw/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"openclaw","user":"proxy-probe","messages":[{"role":"user","content":"Reply with exactly: PONG"}]}'
```

Expected: a chat.completion JSON whose message content is `PONG` (no Authorization header sent from the client — the proxy injected it).

- [ ] **Step 4: Commit**

```bash
git add vite.config.ts
git commit -m "feat: /openclaw proxy — server-side bearer injection, SSE streaming"
```

---

## Task 9: Frontend — OpenClaw client lib + adminMode config

**Files:**
- Create: `src/lib/openclaw.ts`
- Modify: `src/lib/types.ts` (the `AgentConfig` interface at line 75)
- Modify: `src/App.tsx` (the `loadConfig` fallback at line 18)

- [ ] **Step 1: Extend AgentConfig**

In `src/lib/types.ts`, replace the `AgentConfig` interface:

```ts
export interface AgentConfig {
  baseUrl: string
  sessionId: string
  userId: string
  /** When true, chat messages are sent as an admin session (config-by-chat enabled). */
  adminMode: boolean
}
```

In `src/App.tsx` line 18, replace the fallback:

```ts
  const fallback: AgentConfig = { baseUrl: DEFAULT_AGENT_URL, sessionId: 'console-s1', userId: 'console-u1', adminMode: false }
```

- [ ] **Step 2: Write the client lib**

```ts
// src/lib/openclaw.ts
// Chat client for the OpenClaw OpenAI-compatible endpoint, via the /openclaw proxy.
// Streams SSE deltas; extracts the [[gaa:job_id=...]] marker the GAA skill emits
// so the caller can hand the job to the existing GAA poller.

import type { AgentConfig } from './types'

export const JOB_MARKER_RE = /\[\[gaa:job_id=([A-Za-z0-9_-]+)\]\]/

export interface OpenClawReply {
  text: string
  jobId?: string
}

/** Strip the job marker for display (used live during streaming too). */
export function stripMarker(text: string): string {
  return text.replace(JOB_MARKER_RE, '').trim()
}

export async function chatWithOpenClaw(
  message: string,
  cfg: AgentConfig,
  opts?: { onDelta?: (fullTextSoFar: string) => void },
): Promise<OpenClawReply> {
  const user = (cfg.adminMode ? 'admin:' : '') + (cfg.userId || 'console-u1')
  const messages: Array<{ role: string; content: string }> = []
  if (cfg.adminMode) messages.push({ role: 'system', content: 'GAA session role: admin' })
  messages.push({ role: 'user', content: message })

  const res = await fetch('/openclaw/v1/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'openclaw', stream: true, user, messages }),
  })
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '')
    throw new Error(`OpenClaw HTTP ${res.status}: ${detail.slice(0, 300)}`)
  }

  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let text = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    for (;;) {
      const sep = buf.indexOf('\n\n')
      if (sep < 0) break
      const event = buf.slice(0, sep)
      buf = buf.slice(sep + 2)
      for (const line of event.split('\n')) {
        if (!line.startsWith('data:')) continue
        const data = line.slice(5).trim()
        if (!data || data === '[DONE]') continue
        try {
          const j = JSON.parse(data)
          const delta: string = j.choices?.[0]?.delta?.content ?? j.choices?.[0]?.message?.content ?? ''
          if (delta) {
            text += delta
            opts?.onDelta?.(text)
          }
        } catch {
          /* keep-alive / non-JSON line — ignore */
        }
      }
    }
  }

  const m = text.match(JOB_MARKER_RE)
  return { text: stripMarker(text), jobId: m?.[1] }
}
```

- [ ] **Step 3: Verify**

Run: `npm run typecheck`
Expected: no errors (App.tsx and types.ts compile with the new field; nothing else references `AgentConfig` exhaustively).

- [ ] **Step 4: Commit**

```bash
git add src/lib/openclaw.ts src/lib/types.ts src/App.tsx
git commit -m "feat: OpenClaw chat client (SSE + job marker) and adminMode in AgentConfig"
```

---

## Task 10: Frontend — admin toggle in ConnectionPanel

**Files:**
- Modify: `src/components/ConnectionPanel.tsx` (insert after the session/user row, lines 44–53)

- [ ] **Step 1: Add the toggle**

Insert directly after the `</div>` that closes the `conn__row` containing Session id / User id:

```tsx
          <div className="field">
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={config.adminMode}
                onChange={(e) => setConfig({ adminMode: e.target.checked })}
              />
              Admin mode — chat can reconfigure the agent (config-by-chat)
            </label>
          </div>
```

- [ ] **Step 2: Verify**

Run: `npm run typecheck`
Expected: no errors. Then in the dev server, confirm the checkbox renders in the Connection panel and persists across reload (it's part of the localStorage-persisted config).

- [ ] **Step 3: Commit**

```bash
git add src/components/ConnectionPanel.tsx
git commit -m "feat: admin-mode toggle in connection panel"
```

---

## Task 11: Frontend — ChatPanel routes free text through OpenClaw

Free-text chat goes to OpenClaw (streaming); `[[gaa:job_id]]` hands off to the existing poller; OpenClaw failure falls back to the direct GAA path with a notice. CSV onboarding (`onFile`/`confirmOnboard`) stays direct-to-GAA, unchanged.

**Files:**
- Modify: `src/components/chat/ChatPanel.tsx`

- [ ] **Step 1: Rewire `send()`**

Add imports at the top of the file:

```ts
import { chatWithOpenClaw, stripMarker } from '../../lib/openclaw'
```

Add state + streaming helpers inside the component, next to the existing `add` helper:

```ts
  const [openclawBusy, setOpenclawBusy] = useState(false)
  const streamIdxRef = useRef(-1)

  const beginStream = () =>
    setMsgs((x) => {
      streamIdxRef.current = x.length
      return [...x, { role: 'agent', text: '…' }]
    })
  const updateStream = (t: string) =>
    setMsgs((x) => x.map((m, i) => (i === streamIdxRef.current ? { ...m, text: stripMarker(t) || '…' } : m)))
```

Rename the existing `send` function to `sendViaGaa(m: string)` and delete only its preamble — the four lines `const m = message.trim()`, `if (!m || loading || pollerRunning) return`, `add({ role: 'user', text: m })`, and `setText('')`. Everything in the existing function body from `const res = await invoke({ message: m })` down to its closing brace stays exactly as it is today (the error/job/dossier/help/setup handling — see ChatPanel.tsx lines 62–99 pre-edit). The result:

```ts
  async function sendViaGaa(m: string) {
    const res = await invoke({ message: m })
    // unchanged existing body: error guard, poller.resume(toJobStatus(res)) for async
    // jobs, dossier publish for sync analyze, help/setup message handling, JSON fallback
  }
```

Then add the new `send`:

```ts
  async function send(message: string) {
    const m = message.trim()
    if (!m || loading || openclawBusy || pollerRunning) return
    add({ role: 'user', text: m })
    setText('')

    setOpenclawBusy(true)
    beginStream()
    try {
      const reply = await chatWithOpenClaw(m, config, { onDelta: updateStream })
      updateStream(reply.text || 'OK.')
      if (reply.jobId) {
        poller.resume({ job_id: reply.jobId, job_status: 'running', stage: '', activity: [], done: false })
      }
    } catch (err) {
      updateStream(`OpenClaw unreachable (${(err as Error).message}) — sending directly to GAA…`)
      await sendViaGaa(m)
    } finally {
      setOpenclawBusy(false)
    }
  }
```

- [ ] **Step 2: Busy-state + chips + header**

Everywhere the component checks `loading || pollerRunning` (the guard in `onFile`, `confirmOnboard`, the quick-chip `disabled`, the 📎 button, and the Send button), use `loading || openclawBusy || pollerRunning` instead.

Replace the `QUICK` constant:

```ts
const QUICK = ['what is going on with my game?', 'connect my data', 'analyze my recent DAU drop']
const ADMIN_QUICK = ['show current GAA config', 'switch benchmarks to live crawl', 'make reports answer in Vietnamese']
```

and where the chips render, use:

```tsx
        {(config.adminMode ? [...QUICK, ...ADMIN_QUICK] : QUICK).map((q) => (
```

Update the card header hint (line 153) to reflect the new routing: replace `free-text + 📎 CSV → /invocations` with:

```tsx
        <span className="faint">free-text → OpenClaw · 📎 CSV → /invocations</span>
```

- [ ] **Step 3: Verify**

Run: `npm run typecheck`
Expected: no errors.

Manual check with `npm run dev` (needs `.env.local` from Task 8):
1. Chat tab → send "hello" → streamed OpenClaw reply appears progressively.
2. Send "why did my revenue drop last week?" → reply ends without a visible marker; the activity log starts (poller running); on completion the report pane renders.
3. Enable Admin mode → chip "show current GAA config" → reply lists config keys (needs Tasks 12–13 done for live values; before that, OpenClaw will report the GAA admin error — also a valid wiring check).
4. Stop the vite proxy env (`OPENCLAW_URL=` empty) and send a message → error bubble + automatic GAA fallback answer.

- [ ] **Step 4: Commit**

```bash
git add src/components/chat/ChatPanel.tsx
git commit -m "feat: chat routes free text through OpenClaw with job-marker handoff + GAA fallback"
```

---

## Task 12: Deploy GAA with GAA_ADMIN_KEY (checkpoint — needs user)

This redeploys the GAA runtime so the admin actions go live. Follow the `/agentbase-deploy` skill gates (present plan, get explicit confirmation).

- [ ] **Step 1: Generate the admin key and add it to the deploy env**

```bash
openssl rand -hex 24
```

Ask the user to add `GAA_ADMIN_KEY=<generated>` to the env file they deploy with (the same file passed as `--env-file` in previous deploys — do not read it).

- [ ] **Step 2: Build, push, update runtime**

Use the established flow for runtime `runtime-2951893e-745f-40c5-a6d2-66908941f7cb` (see `/agentbase-deploy` Part 1 — user confirms each step). Read the registry URL and repo name from `bash .claude/skills/agentbase/scripts/cr.sh repo get`, and the current image name + flavor from `bash .claude/skills/agentbase/scripts/runtime.sh versions runtime-2951893e-745f-40c5-a6d2-66908941f7cb` (latest version's `imageUrl` / `flavorId` — reuse both, only the tag changes):

```bash
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login
docker build --platform linux/amd64 -t "<registryUrl>/<repoName>/<imageName>:v$(date +%Y%m%d%H%M%S)" .
docker push "<same tag>"
bash .claude/skills/agentbase/scripts/runtime.sh update runtime-2951893e-745f-40c5-a6d2-66908941f7cb \
  --image "<same tag>" --flavor "<current flavorId>" --env-file <env file the user names> --from-cr
```

- [ ] **Step 3: Verify live**

```bash
curl -s -X POST "https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn/invocations" \
  -H 'content-type: application/json' \
  -d '{"action":"admin_get_config","admin_key":"<the key>"}'
```

Expected: `"status": "success"` with the config object. Also verify a wrong key returns `"not authorized"`.

---

## Task 13: Bootstrap OpenClaw + end-to-end demo (checkpoint — needs user)

- [ ] **Step 1: Run the bootstrap with the real GAA_ADMIN_KEY** (Task 7 Step 3 commands, now with the key from Task 12). Expected: all steps green, probe prints PONG.

- [ ] **Step 2: End-to-end demo checklist** (React dev server running, `.env.local` set)

1. **User flow:** Chat: "why did my revenue drop last week?" → OpenClaw streams a one-liner → activity log runs → report pane renders the dossier.
2. **Admin config-by-chat (GAA side):** Admin mode ON → "switch benchmarks to live crawl" → OpenClaw calls `admin_set_config` → "show current GAA config" shows `benchmark_mode: crawl (store)`. Next analysis activity shows a live crawl tier.
3. **Admin config-by-chat (behavior):** "make reports answer in Vietnamese" → OpenClaw calls `admin_set_behavior` → run a new analysis → `main_story`/markdown are in Vietnamese.
4. **Admin config-by-chat (OpenClaw side):** Admin mode ON → "from now on, greet users with a pirate accent" → OpenClaw edits its own SOUL.md → new session greeting reflects it.
5. **Role red-line:** Admin mode OFF → "switch benchmarks to snapshot" → OpenClaw refuses and points to the admin.

- [ ] **Step 3: Update demo docs**

Add the above flow to `docs/demo-script.md` (GAA repo) as the "OpenClaw chat + config-by-chat" section, and commit:

```bash
git add docs/demo-script.md
git commit -m "docs: demo script — OpenClaw chat + config-by-chat flows"
```

---

## Post-plan notes for the executor

- **Order matters:** Tasks 1→6 are sequential (each imports the previous). Task 7 is independent of 8–11. Tasks 12–13 last.
- **Don't put secrets in git or the transcript:** gateway token and GAA_ADMIN_KEY are user-supplied at runtime.
- **The GAA repo has unrelated uncommitted changes** (docs + router tweaks from earlier work). Commit only the files named in each task — never `git add -A`.
- **If `agents.files.set` fails** (Task 7), use the Control-UI fallback documented in that task; everything else still works.
