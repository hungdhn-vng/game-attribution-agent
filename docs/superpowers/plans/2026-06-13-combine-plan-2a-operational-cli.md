# GAA Combine — Plan 2a: Operational CLI (TOML config, onboarding, profile, doctor)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `gaa` CLI fully usable end-to-end without touching Python: replace the SQLite `ConfigStore` with a human-editable `gaa-config.toml`, and add `gaa onboard`, `gaa profile`, `gaa config`, and `gaa doctor` commands.

**Architecture:** A new `gaa.config.GaaConfig` exposes the *same* `resolve(name)→(value,origin)` / `set` / `all_resolved` interface the pipeline's dynamic sources already consume, but backed by a sectioned TOML file (resolution order: file → env → default). Secrets (`perplexity_api_key`) become **env-only** per the design spec. The CLI grows nested subcommands (`onboard propose|confirm`, `profile list|use`, `config get|set`) via argparse `set_defaults(func=…)` dispatch, plus a `doctor` health check. Onboarding ports the logic from the deleted `GraphAgent` into CLI commands operating on server-side CSV paths.

**Tech Stack:** Python 3.11, `tomllib` (stdlib read) + `tomli-w` (write), Pydantic v2, pandas, argparse, pytest.

---

## Scope and relationship to the spec

This is **Plan 2a**, the first half of the roadmap's "Plan 2" (which was too large for one pass). It covers the operational layer from design spec `2026-06-13-single-agent-combine-design.md` §7 (config as a file), §6 operations (`onboard`/`profile`/`config`/`doctor`), and §8.1 (onboarding flow). The second half — **Plan 2b** (the six drilldown primitives, `gaa.lab` Tier 3, tool promotion Tier 2.5) — is a separate plan written after this one.

**Deferred out of 2a (intentional):**
- `synthesis.show_thinking` → `runs/<id>/thinking.md` (spec §8). It requires the real vLLM `reasoning_content` shape, which is only verifiable against live MaaS, and is a demo-only opt-in. It will be added in a focused task during/after Plan 3 (live verification), with its config key introduced then. Keeping it out lets 2a stay fully offline-testable.
- `n_samples` migration into config. It is fixed at pipeline construction (`GAA_N_SAMPLES` env); making it runtime-resolvable is extra scope with no current consumer need. Stays env-based.

**Builds on Plan 1 (merged to `main`):** `gaa.cli.main` (the four commands + `cli_entry`), `gaa.cli.wiring.build_context`/`GaaContext`, `gaa.runs.*`, `gaa.core.*`. The CLI JSON contract from Plan 1's as-built notes is authoritative: top-level `status` ∈ {success-or-lifecycle}, `done` boolean, `error` on failure.

---

## File structure after Plan 2a

```
src/gaa/
├── config.py                   # NEW: GaaConfig (TOML-backed, drop-in for ConfigStore's interface)
├── core/
│   ├── sources/dynamic.py      # MODIFIED: drop the ConfigStore import + type annotation (duck-typed)
│   └── store/config_store.py   # DELETED (replaced by gaa.config)
└── cli/
    ├── wiring.py               # MODIFIED: construct GaaConfig instead of ConfigStore
    ├── main.py                 # MODIFIED: func-dispatch + nested subparsers; new commands
    └── commands/               # NEW: command modules (keeps main.py focused)
        ├── __init__.py
        ├── onboarding.py       # onboard propose|confirm, profile list|use
        ├── config_cmd.py       # config get|set
        └── doctor.py           # doctor

tests/
├── test_gaa_config.py          # NEW (migrated + expanded from test_config_store.py)
├── store/test_config_store.py  # DELETED
├── sources/test_dynamic.py     # MODIFIED: GaaConfig fixture instead of ConfigStore
└── cli/
    ├── test_config_cmd.py      # NEW
    ├── test_doctor.py          # NEW
    ├── test_onboarding.py      # NEW
    └── test_profile.py         # NEW
```

**Design note — why command modules:** Plan 1's `main.py` is ~145 lines with four inline `_cmd_*` functions. Adding onboarding/profile/config/doctor would roughly triple it. To keep each file focused, new command implementations live in `gaa/cli/commands/` and `main.py` only wires parsers → functions. The four Plan 1 commands stay in `main.py` (don't churn working code); new ones go in modules.

**Pre-flight:** `git status` clean on `main`, `.venv/bin/python -m pytest -q` shows **198 passed**. Work on a feature branch off `main`: `git switch -c feat/combine-plan-2a`. Tests run with `.venv/bin/python -m pytest`. The package is editable-installed; after adding the `tomli-w` dependency you must re-run `uv pip install -e . --python .venv/bin/python` (Task 1) so the new dep is importable.

---

### Task 1: `GaaConfig` — TOML-backed runtime config

**Files:**
- Create: `src/gaa/config.py`
- Test: `tests/test_gaa_config.py`
- Modify: `pyproject.toml` (add `tomli-w` dep), `requirements.txt`

- [ ] **Step 1: Add the `tomli-w` dependency and install it**

In `pyproject.toml`, add `"tomli-w>=1.0"` to the `dependencies` list (after `"jinja2==3.*"`). In `requirements.txt`, add a line `tomli-w>=1.0`.
Then install into the venv:
Run: `uv pip install -e . --python .venv/bin/python`
Verify: `.venv/bin/python -c "import tomli_w, tomllib; print('toml libs ok')"` → prints `toml libs ok`.

- [ ] **Step 2: Write the failing test** — create `tests/test_gaa_config.py`:

```python
import pytest

from gaa.config import GaaConfig, KEYS


def _cfg(tmp_path):
    return GaaConfig(str(tmp_path / "gaa-config.toml"))


def test_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("GAA_BENCHMARK_MODE", raising=False)
    assert _cfg(tmp_path).resolve("benchmark_mode") == ("snapshot", "default")


def test_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    assert _cfg(tmp_path).resolve("benchmark_mode") == ("crawl", "env")


def test_stored_value_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    cfg = _cfg(tmp_path)
    cfg.set("benchmark_mode", "snapshot")
    assert cfg.resolve("benchmark_mode") == ("snapshot", "store")
    # persisted across instances (file-backed)
    assert _cfg(tmp_path).resolve("benchmark_mode") == ("snapshot", "store")


def test_set_writes_sectioned_toml(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.set("benchmark_mode", "crawl")
    cfg.set("steam_series_url_tmpl", "https://example.com/{app}.json")
    text = (tmp_path / "gaa-config.toml").read_text()
    assert "[benchmark]" in text and "mode" in text
    assert "[sources]" in text and "steam_series_url_tmpl" in text


def test_clear_removes_key(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.set("benchmark_mode", "crawl")
    cfg.set("benchmark_mode", "")   # clear → falls back to default
    assert cfg.resolve("benchmark_mode") == ("snapshot", "default")


def test_enum_validation(tmp_path):
    with pytest.raises(ValueError):
        _cfg(tmp_path).set("benchmark_mode", "bogus")


def test_url_validation(tmp_path):
    with pytest.raises(ValueError):
        _cfg(tmp_path).set("steam_series_url_tmpl", "not-a-url")


def test_behavior_length_cap(tmp_path):
    with pytest.raises(ValueError):
        _cfg(tmp_path).set("behavior_instructions", "x" * 2001)


def test_secret_is_env_only(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    # cannot be set in the file
    with pytest.raises(ValueError):
        cfg.set("perplexity_api_key", "pplx-123")
    # resolves from env only
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-secret")
    assert cfg.resolve("perplexity_api_key") == ("pplx-secret", "env")


def test_all_resolved_masks_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-abcd1234")
    out = _cfg(tmp_path).all_resolved()
    assert set(out) == set(KEYS)
    assert out["perplexity_api_key"]["value"].endswith("1234")
    assert out["perplexity_api_key"]["value"].startswith("…")


def test_unknown_key_raises(tmp_path):
    with pytest.raises(KeyError):
        _cfg(tmp_path).resolve("nope")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gaa_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.config'`.

- [ ] **Step 4: Write the implementation** — create `src/gaa/config.py`:

```python
"""Runtime-changeable settings backed by a human-editable TOML file.

Resolution order per key: stored value (TOML) → environment variable → built-in
default — the same contract the old SQLite ConfigStore exposed, so the pipeline's
dynamic sources consume it unchanged. Secrets (e.g. the Perplexity key) are
ENV-ONLY: never written to or read from the file (they live in .env).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tomli_w


@dataclass(frozen=True)
class ConfigKey:
    name: str
    section: str          # TOML section; ignored when env_only
    toml_key: str         # key within the section
    env: str
    default: str = ""
    secret: bool = False
    choices: Optional[tuple] = None
    is_url: bool = False
    env_only: bool = False  # secrets: never file-stored or settable
    max_chars: Optional[int] = None


KEYS: dict = {k.name: k for k in [
    ConfigKey("benchmark_mode", "benchmark", "mode", "GAA_BENCHMARK_MODE",
              default="snapshot", choices=("snapshot", "crawl")),
    ConfigKey("roblox_discover_url_tmpl", "sources", "roblox_discover_url_tmpl",
              "GAA_ROBLOX_DISCOVER_URL_TMPL", is_url=True),
    ConfigKey("roblox_series_url_tmpl", "sources", "roblox_series_url_tmpl",
              "GAA_ROBLOX_SERIES_URL_TMPL", is_url=True),
    ConfigKey("steam_series_url_tmpl", "sources", "steam_series_url_tmpl",
              "GAA_STEAM_SERIES_URL_TMPL", is_url=True),
    ConfigKey("signals_url_tmpl", "sources", "signals_url_tmpl",
              "GAA_SIGNALS_URL_TMPL", is_url=True),
    ConfigKey("behavior_instructions", "behavior", "instructions",
              "GAA_BEHAVIOR_INSTRUCTIONS", max_chars=2000),
    ConfigKey("perplexity_api_key", "", "", "PERPLEXITY_API_KEY",
              secret=True, env_only=True),
]}


class GaaConfig:
    """TOML-backed config with env/default fallback. Drop-in for the old ConfigStore."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    # ---- file io ----
    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        with self._path.open("rb") as f:
            return tomllib.load(f)

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("wb") as f:
            tomli_w.dump(data, f)

    # ---- public API (mirrors ConfigStore) ----
    def resolve(self, name: str) -> tuple:
        """Return (value, origin); origin is 'store' | 'env' | 'default'."""
        key = KEYS[name]  # KeyError on unknown key is intentional
        if not key.env_only:
            section = self._read().get(key.section, {})
            if key.toml_key in section:
                return section[key.toml_key], "store"
        env_val = os.environ.get(key.env, "")
        if env_val:
            return env_val, "env"
        return key.default, "default"

    def set(self, name: str, value: Optional[str]) -> None:
        """Set/clear a stored override. None/'' clears it. Secrets are rejected."""
        key = KEYS.get(name)
        if key is None:
            raise KeyError(f"unknown config key: {name!r} (valid: {sorted(KEYS)})")
        if key.env_only:
            raise ValueError(
                f"{name} is a secret — set it in the environment (.env), not the config file")

        data = self._read()
        section = dict(data.get(key.section, {}))

        if value is None or str(value).strip() == "":
            section.pop(key.toml_key, None)
            if section:
                data[key.section] = section
            else:
                data.pop(key.section, None)
            self._write(data)
            return

        value = str(value).strip()
        if key.choices and value not in key.choices:
            raise ValueError(f"{name} must be one of {list(key.choices)}, got {value!r}")
        if key.is_url and not value.startswith(("http://", "https://")):
            raise ValueError(f"{name} must start with http:// or https://")
        if key.max_chars and len(value) > key.max_chars:
            raise ValueError(f"{name} too long ({len(value)} > {key.max_chars} chars)")

        section[key.toml_key] = value
        data[key.section] = section
        self._write(data)

    def all_resolved(self, mask_secrets: bool = True) -> dict:
        out = {}
        for name, key in KEYS.items():
            value, origin = self.resolve(name)
            if mask_secrets and key.secret and value:
                value = "…" + value[-4:]
            out[name] = {"value": value, "origin": origin}
        return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gaa_config.py -v`
Expected: PASS (11 tests).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/config.py tests/test_gaa_config.py pyproject.toml requirements.txt
git commit -m "feat: GaaConfig — TOML-backed runtime config (env-only secrets)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Migrate consumers to `GaaConfig`; delete `ConfigStore`

**Files:**
- Modify: `src/gaa/core/sources/dynamic.py`, `src/gaa/cli/wiring.py`, `tests/sources/test_dynamic.py`
- Delete: `src/gaa/core/store/config_store.py`, `tests/store/test_config_store.py`

- [ ] **Step 1: Decouple `dynamic.py` from the deleted module**

In `src/gaa/core/sources/dynamic.py`:
- Delete the import line `from gaa.core.store.config_store import ConfigStore`.
- Change `def __init__(self, config: ConfigStore, settings: Settings, store) -> None:` → `def __init__(self, config, settings: Settings, store) -> None:` (drop the annotation; the code only calls `config.resolve(...)`, so it is duck-typed).
- Change `def __init__(self, config: ConfigStore, settings: Settings) -> None:` → `def __init__(self, config, settings: Settings) -> None:`.
- (Optional clarity: the two docstrings mentioning "ConfigStore" may be reworded to "config", but this is cosmetic.)

- [ ] **Step 2: Point `wiring.py` at `GaaConfig`**

In `src/gaa/cli/wiring.py`:
- Replace `from gaa.core.store.config_store import ConfigStore` with `from gaa.config import GaaConfig`.
- In the `GaaContext` dataclass, change the field `config: ConfigStore` → `config: GaaConfig`.
- Replace the construction `config = ConfigStore(settings.db_path)` with:
  ```python
  config = GaaConfig(os.environ.get("GAA_CONFIG_PATH", "gaa-config.toml"))
  ```
  (`os` is already imported in `wiring.py`.)

- [ ] **Step 3: Update the `test_dynamic.py` fixture**

In `tests/sources/test_dynamic.py`, replace:
```python
from gaa.core.store.config_store import ConfigStore
```
with
```python
from gaa.config import GaaConfig
```
and the fixture body `return ConfigStore(str(tmp_path / "c.sqlite"))` with `return GaaConfig(str(tmp_path / "gaa-config.toml"))`. Leave the rest of the test unchanged (the `.set`/`.resolve` calls are interface-compatible).

- [ ] **Step 4: Delete the old store and its test**

```bash
git rm src/gaa/core/store/config_store.py tests/store/test_config_store.py
```

- [ ] **Step 5: Confirm no references survive**

Run: `grep -rn "config_store\|ConfigStore" src tests` (ignore `src/gaa.egg-info/`)
Expected: no output outside `egg-info`. If `egg-info` shows it, that is a stale build artifact — ignore (it regenerates on install).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Count = 198 (Plan 1) − (tests in `test_config_store.py`) + 11 (new `test_gaa_config.py`, already committed in Task 1). Report the exact number; there must be 0 failures/errors.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: replace SQLite ConfigStore with GaaConfig across pipeline + wiring

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: CLI dispatch refactor + `gaa config get|set`

Introduces nested subcommands. Converts `main.py` to argparse `set_defaults(func=…)` dispatch (cleaner than the `_DISPATCH` dict once commands nest), without changing the behavior of the four Plan 1 commands.

**Files:**
- Create: `src/gaa/cli/commands/__init__.py` (empty), `src/gaa/cli/commands/config_cmd.py`
- Modify: `src/gaa/cli/main.py`
- Test: `tests/cli/test_config_cmd.py`

- [ ] **Step 1: Write the failing test** — create `tests/cli/test_config_cmd.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _run(argv, tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_config_get_all(tmp_path):
    resp = _run(["config", "get"], tmp_path)
    assert resp["status"] == "success"
    assert "benchmark_mode" in resp["config"]
    assert resp["config"]["benchmark_mode"]["origin"] == "default"


def test_config_set_then_get(tmp_path):
    set_resp = _run(["config", "set", "benchmark_mode", "crawl"], tmp_path)
    assert set_resp["status"] == "success"
    assert set_resp["config"]["benchmark_mode"]["value"] == "crawl"
    get_resp = _run(["config", "get", "benchmark_mode"], tmp_path)
    assert get_resp["value"] == "crawl"
    assert get_resp["origin"] == "store"


def test_config_set_invalid_is_error(tmp_path):
    resp = _run(["config", "set", "benchmark_mode", "bogus"], tmp_path)
    assert resp["status"] == "error"
    assert "one of" in resp["error"]


def test_config_set_secret_rejected(tmp_path):
    resp = _run(["config", "set", "perplexity_api_key", "pplx-x"], tmp_path)
    assert resp["status"] == "error"
    assert "secret" in resp["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/cli/test_config_cmd.py -v`
Expected: FAIL — argparse exits with "invalid choice: 'config'" (the subcommand does not exist yet).

- [ ] **Step 3: Write the config command** — create `src/gaa/cli/commands/__init__.py` (empty) and `src/gaa/cli/commands/config_cmd.py`:

```python
from __future__ import annotations


def cmd_config_get(ctx, args) -> dict:
    if args.key:
        try:
            value, origin = ctx.config.resolve(args.key)
        except KeyError as exc:
            return {"status": "error", "error": str(exc)}
        from gaa.config import KEYS
        if KEYS[args.key].secret and value:
            value = "…" + value[-4:]
        return {"status": "success", "key": args.key, "value": value, "origin": origin}
    return {"status": "success", "config": ctx.config.all_resolved()}


def cmd_config_set(ctx, args) -> dict:
    try:
        ctx.config.set(args.key, args.value)
    except (KeyError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "config": ctx.config.all_resolved()}
```

- [ ] **Step 4: Refactor `main.py` to func-dispatch and register `config`**

In `src/gaa/cli/main.py`:

(a) Add imports near the top (after the existing imports):
```python
from gaa.cli.commands.config_cmd import cmd_config_get, cmd_config_set
```

(b) In `_build_parser()`, attach the existing four commands to functions via `set_defaults`, and add the nested `config` command. Change each existing `sub.add_parser(...)` block to call `.set_defaults(func=...)`. Concretely, after the existing four parsers are defined, set their funcs:
```python
    a.set_defaults(func=_cmd_analyze)
    s.set_defaults(func=_cmd_step)
    st.set_defaults(func=_cmd_status)
    j.set_defaults(func=_cmd_jobs)
```
Then add the `config` command with its own sub-subparsers:
```python
    cfg = sub.add_parser("config", help="get/set runtime configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cg = cfg_sub.add_parser("get", help="show config (all keys, or one)")
    cg.add_argument("key", nargs="?", default=None)
    cg.set_defaults(func=cmd_config_get)
    cs = cfg_sub.add_parser("set", help="set or clear a config key")
    cs.add_argument("key")
    cs.add_argument("value")
    cs.set_defaults(func=cmd_config_set)
```

(c) Delete the `_DISPATCH` dict, and change `main()`'s dispatch line from `result = _DISPATCH[args.command](ctx, args)` to:
```python
        result = args.func(ctx, args)
```
(The `func` attribute is set on every leaf subparser, so `args.func` always resolves; argparse already errors on a missing/invalid subcommand because the subparsers are `required=True`.)

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_config_cmd.py tests/cli/test_cli.py -v`
Expected: PASS — the four new config tests AND the four Plan 1 CLI tests (proving the dispatch refactor preserved behavior).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → expect green.
```bash
git add src/gaa/cli/main.py src/gaa/cli/commands/__init__.py src/gaa/cli/commands/config_cmd.py tests/cli/test_config_cmd.py
git commit -m "feat: gaa config get/set + argparse func-dispatch for nested subcommands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `gaa doctor` — health check

**Files:**
- Create: `src/gaa/cli/commands/doctor.py`
- Modify: `src/gaa/cli/main.py` (register `doctor`)
- Test: `tests/cli/test_doctor.py`

- [ ] **Step 1: Write the failing test** — create `tests/cli/test_doctor.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _run(tmp_path, monkeypatch, with_key: bool):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    if with_key:
        monkeypatch.setenv("LLM_API_KEY", "k")
    else:
        monkeypatch.delenv("LLM_API_KEY", raising=False)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["doctor"], today="2026-06-13")
    return json.loads(buf.getvalue())


def test_doctor_reports_checks(tmp_path, monkeypatch):
    resp = _run(tmp_path, monkeypatch, with_key=True)
    names = {c["name"] for c in resp["checks"]}
    assert "dep:statsmodels" in names
    assert "dep:ruptures" in names
    assert "config" in names
    assert "active_profile" in names
    assert "llm_credentials" in names
    # deps + config + stores are present and ok in a clean env
    assert resp["ok"] is True  # no active profile / key are warnings, not errors


def test_doctor_hard_ok_independent_of_warnings(tmp_path, monkeypatch):
    # No profile, no key → still ok:true (those are warn-level), status success
    resp = _run(tmp_path, monkeypatch, with_key=False)
    assert resp["status"] == "success"
    assert resp["ok"] is True
    llm = next(c for c in resp["checks"] if c["name"] == "llm_credentials")
    assert llm["ok"] is False and llm["level"] == "warn"
    prof = next(c for c in resp["checks"] if c["name"] == "active_profile")
    assert prof["ok"] is False and prof["level"] == "warn"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/cli/test_doctor.py -v`
Expected: FAIL — argparse "invalid choice: 'doctor'".

- [ ] **Step 3: Write the doctor command** — create `src/gaa/cli/commands/doctor.py`:

```python
from __future__ import annotations

import importlib

_REQUIRED_DEPS = [
    "pandas", "pyarrow", "statsmodels", "ruptures", "plotly", "jinja2", "langchain_openai",
]


def cmd_doctor(ctx, args) -> dict:
    """Health check: deps + config + stores are hard (error-level); active
    profile + LLM credentials are warn-level (missing is OK for a fresh setup)."""
    checks: list[dict] = []

    for mod in _REQUIRED_DEPS:
        try:
            importlib.import_module(mod)
            checks.append({"name": f"dep:{mod}", "ok": True, "level": "error", "detail": "importable"})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": f"dep:{mod}", "ok": False, "level": "error", "detail": str(exc)})

    try:
        ctx.config.all_resolved()
        checks.append({"name": "config", "ok": True, "level": "error",
                       "detail": str(ctx.config._path)})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "config", "ok": False, "level": "error", "detail": str(exc)})

    # Stores were already constructed by build_context; their roots exist if we got here.
    checks.append({"name": "stores", "ok": True, "level": "error",
                   "detail": f"runs={ctx.runs.path_for('').parent}"})

    active = ctx.profiles.get_active()
    checks.append({"name": "active_profile", "ok": active is not None, "level": "warn",
                   "detail": active.name if active else "none — run `gaa onboard` first"})

    has_key = bool(ctx.settings.llm_api_key)
    checks.append({"name": "llm_credentials", "ok": has_key, "level": "warn",
                   "detail": "set" if has_key else "LLM_API_KEY unset (synthesis will fail)"})

    ok = all(c["ok"] for c in checks if c["level"] == "error")
    return {"status": "success" if ok else "error", "ok": ok, "checks": checks}
```

- [ ] **Step 4: Register `doctor` in `main.py`**

In `src/gaa/cli/main.py`: add import `from gaa.cli.commands.doctor import cmd_doctor`, and in `_build_parser()` add:
```python
    d = sub.add_parser("doctor", help="check environment health")
    d.set_defaults(func=cmd_doctor)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_doctor.py -v`
Expected: PASS (2 tests). Note: `ctx.runs.path_for('')` is used only to derive the runs root for a detail string; if it misbehaves on an empty id, instead use `ctx.runs._root` is private — prefer adding nothing fragile: if `path_for('')` is awkward, change that detail line to `"detail": "ok"`. Keep the check itself (`ok: True`).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/main.py src/gaa/cli/commands/doctor.py tests/cli/test_doctor.py
git commit -m "feat: gaa doctor — environment health check (error vs warn levels)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `gaa onboard propose` and `gaa onboard confirm`

Ports the deleted `GraphAgent` onboarding flow into CLI commands operating on a server-side CSV path. `propose` shows the LLM the first 20 rows and returns a `ColumnMapping`; `confirm` ingests the file through the adapter, persists metrics + profile, and activates it.

**Files:**
- Create: `src/gaa/cli/commands/onboarding.py`
- Modify: `src/gaa/cli/main.py` (register `onboard`)
- Test: `tests/cli/test_onboarding.py`

- [ ] **Step 1: Write the failing test** — create `tests/cli/test_onboarding.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.profile_store import ProfileStore
from gaa.core.store.metrics_store import MetricsStore


# Profiler.propose returns ColumnMapping(**raw); this preset matches the CSV below.
_MAPPING_PRESET = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}


def _write_csv(tmp_path):
    csv = tmp_path / "metrics.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)
    return str(csv)


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")


def _run(argv, llm, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_onboard_propose_returns_mapping(tmp_path):
    csv = _write_csv(tmp_path)
    resp = _run(["onboard", "propose", "--csv", csv], FakeLLM(_MAPPING_PRESET), tmp_path)
    assert resp["status"] == "success"
    assert resp["mapping"]["date_col"] == "day"
    assert resp["mapping"]["metric_cols"] == {"dau": "dau"}
    assert "message" in resp


def test_onboard_confirm_persists_and_activates(tmp_path):
    csv = _write_csv(tmp_path)
    mapping_json = json.dumps(_MAPPING_PRESET)
    resp = _run(
        ["onboard", "confirm", "--csv", csv, "--mapping", mapping_json,
         "--name", "MyGame", "--platform", "roblox", "--genre", "survival"],
        FakeLLM(_MAPPING_PRESET), tmp_path,
    )
    assert resp["status"] == "success"
    assert resp["name"] == "MyGame"
    assert resp["row_count"] == 4
    assert resp["metrics"] == ["dau"]
    # persisted + active
    ps = ProfileStore(os.environ["GAA_DB_PATH"])
    assert ps.get_active().name == "MyGame"
    df = MetricsStore(os.environ["GAA_CACHE_DIR"] + "/metrics").load("MyGame")
    assert len(df) == 4


def test_onboard_confirm_bad_mapping_is_error(tmp_path):
    csv = _write_csv(tmp_path)
    resp = _run(
        ["onboard", "confirm", "--csv", csv, "--mapping", "{not json}",
         "--name", "X", "--platform", "p", "--genre", "g"],
        FakeLLM(_MAPPING_PRESET), tmp_path,
    )
    assert resp["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/cli/test_onboarding.py -v`
Expected: FAIL — argparse "invalid choice: 'onboard'".

- [ ] **Step 3: Write the onboarding commands** — create `src/gaa/cli/commands/onboarding.py`:

```python
from __future__ import annotations

import json

import pandas as pd

from gaa.core.adapters.csv_adapter import CSVAdapter
from gaa.core.adapters.roblox_adapter import RobloxAdapter
from gaa.core.schema.profile import ColumnMapping, GameProfile


def _adapter(name: str):
    return RobloxAdapter() if name == "roblox" else CSVAdapter()


def cmd_onboard_propose(ctx, args) -> dict:
    try:
        sample = pd.read_csv(args.csv, nrows=20)
        mapping = ctx.profiler.propose(sample)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {
        "status": "success",
        "mapping": mapping.model_dump(),
        "message": ctx.profiler.confirmation_message(mapping),
    }


def cmd_onboard_confirm(ctx, args) -> dict:
    try:
        mapping = ColumnMapping(**json.loads(args.mapping))
        raw = pd.read_csv(args.csv)
        df = _adapter(args.adapter).load(raw, mapping)
        ctx.metrics.save(args.name, df)
        ctx.profiles.save(GameProfile(
            name=args.name, platform=args.platform, genre=args.genre, mapping=mapping))
        ctx.profiles.set_active(args.name)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {
        "status": "success",
        "name": args.name,
        "row_count": int(len(df)),
        "metrics": sorted(df["metric"].unique().tolist()),
    }
```

- [ ] **Step 4: Register `onboard` in `main.py`**

Add import `from gaa.cli.commands.onboarding import cmd_onboard_propose, cmd_onboard_confirm`. In `_build_parser()`:
```python
    ob = sub.add_parser("onboard", help="connect a game's data")
    ob_sub = ob.add_subparsers(dest="onboard_command", required=True)
    obp = ob_sub.add_parser("propose", help="LLM proposes a column mapping from the first rows")
    obp.add_argument("--csv", required=True)
    obp.add_argument("--adapter", choices=["csv", "roblox"], default="csv")
    obp.set_defaults(func=cmd_onboard_propose)
    obc = ob_sub.add_parser("confirm", help="ingest the file with a confirmed mapping")
    obc.add_argument("--csv", required=True)
    obc.add_argument("--mapping", required=True, help="ColumnMapping as a JSON string")
    obc.add_argument("--name", required=True)
    obc.add_argument("--platform", required=True)
    obc.add_argument("--genre", required=True)
    obc.add_argument("--adapter", choices=["csv", "roblox"], default="csv")
    obc.set_defaults(func=cmd_onboard_confirm)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_onboarding.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/main.py src/gaa/cli/commands/onboarding.py tests/cli/test_onboarding.py
git commit -m "feat: gaa onboard propose/confirm — CSV onboarding via CLI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `gaa profile list` and `gaa profile use`

**Files:**
- Modify: `src/gaa/cli/commands/onboarding.py` (add profile functions — they share the profile store), `src/gaa/cli/main.py` (register `profile`)
- Test: `tests/cli/test_profile.py`

- [ ] **Step 1: Write the failing test** — create `tests/cli/test_profile.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.store.profile_store import ProfileStore


def _seed_two_profiles(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    ps = ProfileStore(os.environ["GAA_DB_PATH"])
    m = ColumnMapping(date_col="d", metric_cols={"dau": "dau"}, dim_cols={})
    ps.save(GameProfile(name="Alpha", platform="roblox", genre="rpg", mapping=m))
    ps.save(GameProfile(name="Beta", platform="steam", genre="fps", mapping=m))
    ps.set_active("Alpha")


def _run(argv, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_profile_list(tmp_path):
    _seed_two_profiles(tmp_path)
    resp = _run(["profile", "list"], tmp_path)
    assert resp["status"] == "success"
    assert set(resp["profiles"]) == {"Alpha", "Beta"}
    assert resp["active"] == "Alpha"


def test_profile_use_switches_active(tmp_path):
    _seed_two_profiles(tmp_path)
    resp = _run(["profile", "use", "Beta"], tmp_path)
    assert resp["status"] == "success"
    assert resp["active"] == "Beta"
    assert _run(["profile", "list"], tmp_path)["active"] == "Beta"


def test_profile_use_unknown_is_error(tmp_path):
    _seed_two_profiles(tmp_path)
    resp = _run(["profile", "use", "Nope"], tmp_path)
    assert resp["status"] == "error"
    assert "unknown profile" in resp["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/cli/test_profile.py -v`
Expected: FAIL — argparse "invalid choice: 'profile'".

- [ ] **Step 3: Add profile functions** — append to `src/gaa/cli/commands/onboarding.py`:

```python
def cmd_profile_list(ctx, args) -> dict:
    active = ctx.profiles.get_active()
    return {
        "status": "success",
        "profiles": ctx.profiles.list_names(),
        "active": active.name if active else None,
    }


def cmd_profile_use(ctx, args) -> dict:
    if args.name not in ctx.profiles.list_names():
        return {"status": "error", "error": f"unknown profile: {args.name!r}"}
    ctx.profiles.set_active(args.name)
    return {"status": "success", "active": args.name}
```

- [ ] **Step 4: Register `profile` in `main.py`**

Add to the onboarding import: `from gaa.cli.commands.onboarding import (cmd_onboard_propose, cmd_onboard_confirm, cmd_profile_list, cmd_profile_use)`. In `_build_parser()`:
```python
    pf = sub.add_parser("profile", help="manage game profiles")
    pf_sub = pf.add_subparsers(dest="profile_command", required=True)
    pfl = pf_sub.add_parser("list", help="list profiles + the active one")
    pfl.set_defaults(func=cmd_profile_list)
    pfu = pf_sub.add_parser("use", help="set the active profile")
    pfu.add_argument("name")
    pfu.set_defaults(func=cmd_profile_use)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_profile.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/main.py src/gaa/cli/commands/onboarding.py tests/cli/test_profile.py
git commit -m "feat: gaa profile list/use

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: End-to-end integration test + console smoke

Proves the whole operational loop works through the real `gaa` binary: onboard a CSV → set config → doctor → analyze to done.

**Files:**
- Test: `tests/cli/test_operational_e2e.py`

- [ ] **Step 1: Write the end-to-end test** — create `tests/cli/test_operational_e2e.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.benchmark_store import BenchmarkStore


_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {
    "main_story": "DAU dropped — internal.",
    "rationale": "SEA drove it.",
    "causes": {"internal": [{"claim": "SEA fell", "evidence_ids": ["L1"], "likelihood": "Likely"}],
               "market": []},
    "scenarios": [], "risks": [], "assumptions_and_gaps": [],
}


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")


def _run(argv, llm, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_full_operational_loop(tmp_path):
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)

    # 1. onboard
    r = _run(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
              "--name", "SurvivalGame", "--platform", "roblox", "--genre", "survival"],
             FakeLLM(_MAPPING), tmp_path)
    assert r["status"] == "success"

    # benchmark control series so the counterfactual has data
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})

    # 2. config
    assert _run(["config", "set", "benchmark_mode", "snapshot"], FakeLLM(_SYNTH), tmp_path)["status"] == "success"

    # 3. doctor (no key → warn-level only, still ok)
    assert _run(["doctor"], FakeLLM(_SYNTH), tmp_path)["ok"] is True

    # 4. analyze to done
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)
    rid = started["run_id"]
    done = started["done"]
    for _ in range(10):
        if done:
            break
        done = _run(["step", rid], FakeLLM(_SYNTH), tmp_path)["done"]
    assert done, "analysis did not reach done"
    final = _run(["status", rid], FakeLLM(_SYNTH), tmp_path)
    assert final["status"] == "done"
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/cli/test_operational_e2e.py -v`
Expected: PASS. If `analyze` errors, inspect `final["error"]`/activity and fix the real cause (do not weaken assertions).

- [ ] **Step 3: Real console smoke**

```bash
uv pip install -e . --python .venv/bin/python   # ensure tomli-w is in the installed env
rm -rf /tmp/gaa-2a && mkdir -p /tmp/gaa-2a
export GAA_CACHE_DIR=/tmp/gaa-2a/cache GAA_DB_PATH=/tmp/gaa-2a/gaa.sqlite GAA_CONFIG_PATH=/tmp/gaa-2a/gaa-config.toml
.venv/bin/gaa doctor
.venv/bin/gaa config set benchmark_mode crawl
.venv/bin/gaa config get benchmark_mode
cat /tmp/gaa-2a/gaa-config.toml
.venv/bin/gaa profile list
```
Expected: `doctor` returns `ok:true`; `config set` then `config get` shows `value:"crawl", origin:"store"`; the TOML file contains `[benchmark]` / `mode = "crawl"`; `profile list` returns an empty list with `active:null`. No tracebacks.

- [ ] **Step 4: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green; record the final count.
```bash
git add tests/cli/test_operational_e2e.py
git commit -m "test: end-to-end operational CLI loop (onboard→config→doctor→analyze)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review (performed against the spec)

- **Config as a visible file (spec §7):** `GaaConfig` TOML, file→env→default, validated writes, secrets env-only — Task 1; consumers migrated, `ConfigStore` deleted — Task 2. ✓
- **`gaa config get/set` (spec §6 operations):** Task 3. ✓
- **`gaa doctor` (spec §6, installer dependency):** Task 4, with error/warn levels so its exit code is meaningful for Plan 3's installer. ✓
- **Zero-code onboarding (spec §6, §8.1):** `onboard propose`/`confirm` port the human-in-the-loop flow — Task 5. ✓
- **`gaa profile list/use` (spec §6):** Task 6. ✓
- **End-to-end usability:** Task 7 proves onboard→config→doctor→analyze through the real entry point. ✓
- **Deferred (documented):** `show_thinking`/`thinking.md` and `n_samples`-in-config — noted in scope section, not built. The TOML registry intentionally omits a `show_thinking` key until its capture mechanism is built (no dead config keys).
- **Type/interface consistency:** `GaaConfig` exposes exactly `resolve(name)->(value,origin)`, `set(name,value)`, `all_resolved(mask_secrets=True)` — the three methods `DynamicRefresher`/`DynamicSignals` (via `.resolve`) and the new CLI consume. `GaaContext.config` is `GaaConfig` everywhere. Command functions all take `(ctx, args)` and return the Plan 1 `{status, …}` contract.

No placeholders, TODOs, or undefined references.

---

## After Plan 2a → Plan 2b (the power tools)

Written as its own plan once 2a merges. Scope: the six drilldown primitives (`gaa detect|segments|market|signals|synth|report --run <id>` reading a run's plan-state and appending provenance-tagged ledger entries), `gaa.lab` (Tier 3 read-only data API + `scratch/` convention + `adhoc:` evidence capped at Moderate), and tool promotion (Tier 2.5: `gaa tools promote|run|list|…`, the `data/tools/` md5-frozen registry). Plus the deferred `synthesis.show_thinking` → `thinking.md` once it can be live-verified.
