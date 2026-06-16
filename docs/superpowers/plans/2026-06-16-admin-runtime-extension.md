# Admin Runtime Extension + Non-Admin Lockdown — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an authenticated admin full container power + the ability to register MCP servers and secrets at runtime via chat, while locking non-admin down to analysis-only — closing the live RCE/secret hole in the process.

**Architecture:** Two OpenClaw gateways in one container — a non-admin gateway whose tools are allow-listed to `gaa__*` + shared registered servers, and an admin gateway with the full built-in suite + admin-gated management tools. The front door routes `/chat` by `is_admin`. Admin-registered MCP servers + their secrets persist to vStorage and are merged into both gateways' configs.

**Tech Stack:** Python 3.11, FastAPI, the MCP Python SDK, OpenClaw (Node) gateway, boto3→vStorage, pytest. Spec: `docs/superpowers/specs/2026-06-16-admin-runtime-extension-design.md`.

**Read before starting:** the spec above; `src/gaa/server/openclaw_config.py`, `src/gaa/server/actions.py`, `src/gaa/mcp/tools.py`, `src/gaa/mcp/server.py`, `src/gaa/persist.py`, `src/gaa/server/app.py`, `src/gaa/server/openclaw_client.py`, `scripts/entrypoint.sh`.

**Test command:** `source .venv/bin/activate && python -m pytest -q` (full suite must stay green; 368 tests at plan time).

---

## File Structure

**Create:**
- `src/gaa/server/extensions.py` — MCP-server registry + secret store (load/save, validation, vStorage-persisted paths). One responsibility: durable, validated storage of admin-registered servers and secrets.
- `src/gaa/cli/commands/extensions_cmd.py` — the six management action handlers (`cmd_mcp_add/remove/list`, `cmd_secret_set/unset/list`) in the `(ctx, args) -> dict` shape the dispatch layer expects.
- `tests/server/test_extensions.py`, `tests/cli/test_extensions_cmd.py`, `tests/server/test_config_profiles.py`, `tests/server/test_chat_routing.py`, `tests/mcp/test_admin_tools.py`.
- `docs/spikes/2026-06-16-openclaw-tools-reload.md` — spike findings (Phase 0 output).

**Modify:**
- `src/gaa/server/openclaw_config.py` — `render_config(profile=…)`: per-profile tool policy + `GAA_MCP_ADMIN` + registry merge + secret injection.
- `src/gaa/mcp/tools.py` — add the six management tool specs.
- `src/gaa/server/actions.py` — register the six handlers; extend `ADMIN_ACTIONS` / `MUTATING_ACTIONS`.
- `src/gaa/persist.py` — add registry + secrets to `_durable_items`.
- `src/gaa/server/openclaw_client.py` — target URL per gateway.
- `src/gaa/server/app.py` — `/chat` routes by `is_admin`.
- `scripts/entrypoint.sh` — render + launch two gateways; reload handling.
- `Dockerfile` — env for the two gateway config dirs / ports / URLs.

---

## Phase 0 — Spikes (resolve OpenClaw unknowns FIRST; these gate Phases 3–4)

These are investigations, not TDD. Record findings in `docs/spikes/2026-06-16-openclaw-tools-reload.md`. **Phases 3 and 4 must be adjusted to match what these find.** Use the combined image already on the CR (`vcr.vngcloud.vn/111480-abp111723/gaa-custom-agent:v20260615-234137`) so the gaa MCP server is present.

### Task 0.1 (Spike A): Correct tool-restriction syntax

`tools.deny:["group:openclaw"]` did NOT remove `exec`/`read`/`write` (only a subset). Find the config that limits a gateway to *only* the gaa tools.

- [ ] **Step 1: Run the image locally with a probe config**

```bash
docker run --rm -it --entrypoint sh \
  vcr.vngcloud.vn/111480-abp111723/gaa-custom-agent:v20260615-234137 -c '
  openclaw --help 2>&1 | head -40
  # inspect the tools config schema / group names OpenClaw recognizes:
  openclaw config schema 2>/dev/null | grep -iA3 -e tools -e allow -e deny | head -60 || true
  openclaw tools list 2>/dev/null | head -60 || true
'
```

- [ ] **Step 2: Try an allow-list config and verify built-ins disappear**

Render a config with a candidate allow-list (try, in order, until one limits the surface to only gaa tools): `{"tools":{"allow":["gaa"]}}`, then `{"tools":{"allow":["gaa__*"]}}`, then an explicit id list `{"tools":{"allow":["gaa__analyze", … all gaa ids]}}`. For each, boot the gateway, then via the HTTP completions endpoint ask the agent "list every tool you can call" and confirm `exec`/`read`/`write` are **absent**.

- [ ] **Step 3: Record the winning syntax** in the spike doc: the exact `tools` block that yields only gaa tools, and whether server-name (`gaa`), wildcard (`gaa__*`), or explicit-id form is required. **This value is consumed by Task 8 (`render_config` nonadmin profile).**

### Task 0.2 (Spike B): MCP server reload behavior

- [ ] **Step 1: Test hot-add.** With a gateway running, append a new server to `mcp.servers` in its `openclaw.json` and check whether OpenClaw exposes its tools without a restart (look for a reload command: `openclaw gateway reload`/`openclaw mcp reload`, a SIGHUP handler, or a control API). 
- [ ] **Step 2: If no hot-reload,** confirm a clean process restart picks up the new server (kill the gateway process, relaunch with the same config dir, list tools).
- [ ] **Step 3: Record** the chosen reload mechanism in the spike doc. **Consumed by Task 12 (reload trigger) and Task 11 (entrypoint).**

### Task 0.3 (Spike C): Two gateways + resources + layout

- [ ] **Step 1: Run two gateways** in one container on ports 18789/18790 with separate config dirs (`/home/node/.openclaw-nonadmin`, `/home/node/.openclaw-admin`), each pointing its MCP server at the **shared** `GAA_CACHE_DIR`. Confirm both serve `/v1/chat/completions` and both reach the gaa MCP tools.
- [ ] **Step 2: Pick the snapshot-safe workspace layout.** `persist._durable_items` snapshots `OPENCLAW_HOME/workspace`. Decide the canonical persona-workspace dir both gateways use (e.g. a shared `OPENCLAW_HOME=/home/node/.openclaw` with `workspace/`, and per-gateway config dirs holding only `openclaw.json`). Record so `persist.py` keeps **one** unambiguous snapshot target.
- [ ] **Step 3: Measure peak memory** of (2 gateways + 2 MCP servers + uvicorn) under a chat turn. If it exceeds the 2×4 flavor, note the flavor bump needed for deploy (Task 13). Record numbers in the spike doc.

---

## Phase 1 — Registry + secret store

### Task 1: Registry + secret store module

**Files:**
- Create: `src/gaa/server/extensions.py`
- Test: `tests/server/test_extensions.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/server/test_extensions.py
import json, os, stat
import pytest
from gaa.server import extensions as ext


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ext, "_dir", lambda: tmp_path)
    yield


def test_add_list_remove_server():
    ext.add_server(name="crawler", command="npx", args=["x-mcp"], url=None,
                   env={"CRAWLER_KEY": "CRAWLER_KEY"})
    assert [s["name"] for s in ext.list_servers()] == ["crawler"]
    ext.remove_server("crawler")
    assert ext.list_servers() == []


def test_add_server_rejects_bad_name():
    with pytest.raises(ValueError):
        ext.add_server(name="has space", command="x", args=[], url=None, env={})


def test_add_server_requires_command_or_url():
    with pytest.raises(ValueError):
        ext.add_server(name="x", command=None, args=[], url=None, env={})


def test_secret_roundtrip_and_names_only():
    ext.set_secret("CRAWLER_KEY", "s3cr3t-value")
    assert ext.list_secret_names() == ["CRAWLER_KEY"]          # names only — never values
    assert ext.get_secret("CRAWLER_KEY") == "s3cr3t-value"
    ext.unset_secret("CRAWLER_KEY")
    assert ext.list_secret_names() == []


def test_secret_file_mode_600(tmp_path):
    ext.set_secret("K", "v")
    mode = stat.S_IMODE(os.stat(ext.secrets_path()).st_mode)
    assert mode == 0o600
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/server/test_extensions.py -q`
Expected: FAIL (module/functions missing).

- [ ] **Step 3: Implement**

```python
# src/gaa/server/extensions.py
"""Durable registry of admin-registered MCP servers + a secret store.

Both files live under GAA_CACHE_DIR so persist._durable_items snapshots them to
vStorage. Secrets file is mode 0600 and its values are never listed/logged.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def _dir() -> Path:
    d = Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "extensions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> str:
    return str(_dir() / "mcp_registry.json")


def secrets_path() -> str:
    return str(_dir() / "mcp_secrets.json")


def _read(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def list_servers() -> list[dict]:
    return _read(registry_path(), [])


def add_server(*, name: str, command, args, url, env) -> dict:
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"invalid server name: {name!r} (use [a-z0-9_], <=32)")
    if not command and not url:
        raise ValueError("server needs a command or a url")
    servers = [s for s in list_servers() if s["name"] != name]
    entry = {"name": name, "command": command, "args": list(args or []),
             "url": url, "env": dict(env or {})}
    servers.append(entry)
    with open(registry_path(), "w") as f:
        json.dump(servers, f, indent=2)
    return entry


def remove_server(name: str) -> bool:
    servers = list_servers()
    kept = [s for s in servers if s["name"] != name]
    with open(registry_path(), "w") as f:
        json.dump(kept, f, indent=2)
    return len(kept) != len(servers)


def _read_secrets() -> dict:
    return _read(secrets_path(), {})


def _write_secrets(d: dict) -> None:
    path = secrets_path()
    with open(path, "w") as f:
        json.dump(d, f)
    os.chmod(path, 0o600)


def set_secret(name: str, value: str) -> None:
    if not _NAME_RE.match((name or "").lower()):
        raise ValueError(f"invalid secret name: {name!r}")
    d = _read_secrets(); d[name] = value; _write_secrets(d)


def unset_secret(name: str) -> bool:
    d = _read_secrets()
    existed = name in d
    d.pop(name, None); _write_secrets(d)
    return existed


def get_secret(name: str):
    return _read_secrets().get(name)


def list_secret_names() -> list[str]:
    return sorted(_read_secrets().keys())
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/server/test_extensions.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/extensions.py tests/server/test_extensions.py
git commit -m "feat(extensions): durable MCP-server registry + secret store"
```

### Task 2: Persist registry + secrets to vStorage

**Files:**
- Modify: `src/gaa/persist.py:58-73` (`_durable_items`)
- Test: `tests/test_persist.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_persist.py`)

```python
def test_durable_items_include_extensions(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    from gaa.cli.wiring import build_context
    from gaa import persist
    ctx = build_context()
    arcnames = {a for a, _p, _d in persist._durable_items(ctx)}
    assert "mcp_registry.json" in arcnames
    assert "mcp_secrets.json" in arcnames
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_persist.py::test_durable_items_include_extensions -q`
Expected: FAIL (arcnames missing).

- [ ] **Step 3: Implement** — in `_durable_items`, add the two files (import locally to avoid a cycle):

```python
    from gaa.server import extensions
    ...
    return [
        ("config.toml", Path(ctx.config._path), False),
        ("profiles.sqlite", Path(ctx.settings.db_path), False),
        ("metrics", cache / "metrics", True),
        ("tools", tools, True),
        ("openclaw_workspace", openclaw_home / "workspace", True),
        ("mcp_registry.json", Path(extensions.registry_path()), False),
        ("mcp_secrets.json", Path(extensions.secrets_path()), False),
    ]
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_persist.py -q` (existing persist tests + the new one all pass).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/persist.py tests/test_persist.py
git commit -m "feat(persist): snapshot the MCP registry + secret store to vStorage"
```

---

## Phase 2 — Management tools (handlers + MCP specs)

### Task 3: Management action handlers + dispatch registration

**Files:**
- Create: `src/gaa/cli/commands/extensions_cmd.py`
- Modify: `src/gaa/server/actions.py:14-23` (imports), `:43-69` (`_HANDLERS`), `:76-85` (`ADMIN_ACTIONS`, `MUTATING_ACTIONS`)
- Test: `tests/cli/test_extensions_cmd.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/cli/test_extensions_cmd.py
import types
from gaa.server import actions


def _ns(**kw):
    ns = types.SimpleNamespace(**kw)
    ns.__class__ = type("A", (types.SimpleNamespace,), {"__getattr__": lambda s, n: None})
    return ns


def test_dispatch_gates_management_tools_non_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.cli.wiring import build_context
    ctx = build_context()
    r = actions.dispatch(ctx, "mcp_add", {"name": "c", "command": "npx"}, is_admin=False)
    assert r["status"] == "error" and "admin" in r["error"]


def test_mcp_add_and_list_as_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.cli.wiring import build_context
    ctx = build_context()
    r = actions.dispatch(ctx, "mcp_add",
                         {"name": "crawler", "command": "npx", "args": ["x"],
                          "env": {"K": "K"}}, is_admin=True)
    assert r["status"] == "success"
    lst = actions.dispatch(ctx, "mcp_list", {}, is_admin=True)
    assert "crawler" in [s["name"] for s in lst["servers"]]


def test_secret_set_list_hides_values(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.cli.wiring import build_context
    ctx = build_context()
    actions.dispatch(ctx, "secret_set", {"name": "K", "value": "v"}, is_admin=True)
    r = actions.dispatch(ctx, "secret_list", {}, is_admin=True)
    assert r["names"] == ["K"]
    assert "v" not in str(r)             # value must never appear


def test_management_tools_are_admin_and_mutating():
    for a in ("mcp_add", "mcp_remove", "secret_set", "secret_unset"):
        assert a in actions.ADMIN_ACTIONS and a in actions.MUTATING_ACTIONS
    for a in ("mcp_list", "secret_list"):
        assert a in actions.ADMIN_ACTIONS and a not in actions.MUTATING_ACTIONS
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/cli/test_extensions_cmd.py -q`
Expected: FAIL (handlers/actions missing).

- [ ] **Step 3: Implement the handlers**

```python
# src/gaa/cli/commands/extensions_cmd.py
"""Admin management actions: register/unregister MCP servers and manage secrets.
Handlers take (ctx, args) where args is an argparse-Namespace-like object whose
unset attributes are None (see gaa.server.actions._Args)."""
from __future__ import annotations

from gaa.server import extensions


def cmd_mcp_add(ctx, args) -> dict:
    try:
        entry = extensions.add_server(
            name=args.name, command=args.command, args=args.args or [],
            url=args.url, env=args.env or {})
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "server": entry,
            "note": "Reloading the runtime so the new tools become available."}


def cmd_mcp_remove(ctx, args) -> dict:
    removed = extensions.remove_server(args.name)
    return {"status": "success", "removed": removed}


def cmd_mcp_list(ctx, args) -> dict:
    return {"status": "success", "servers": extensions.list_servers()}


def cmd_secret_set(ctx, args) -> dict:
    if not args.value:
        return {"status": "error", "error": "value is required"}
    try:
        extensions.set_secret(args.name, args.value)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "name": args.name}   # never echo the value


def cmd_secret_unset(ctx, args) -> dict:
    return {"status": "success", "removed": extensions.unset_secret(args.name)}


def cmd_secret_list(ctx, args) -> dict:
    return {"status": "success", "names": extensions.list_secret_names()}
```

- [ ] **Step 4: Register in `src/gaa/server/actions.py`**

Add the import after the other command imports (line ~23):

```python
from gaa.cli.commands.extensions_cmd import (
    cmd_mcp_add, cmd_mcp_remove, cmd_mcp_list,
    cmd_secret_set, cmd_secret_unset, cmd_secret_list)
```

Add to `_HANDLERS`:

```python
    "mcp_add": cmd_mcp_add,
    "mcp_remove": cmd_mcp_remove,
    "mcp_list": cmd_mcp_list,
    "secret_set": cmd_secret_set,
    "secret_unset": cmd_secret_unset,
    "secret_list": cmd_secret_list,
```

Extend the sets:

```python
ADMIN_ACTIONS = {
    "config_set", "profile_use", "tools_promote", "tools_run",
    "tools_remove", "tools_import",
    "mcp_add", "mcp_remove", "mcp_list", "secret_set", "secret_unset", "secret_list",
}
MUTATING_ACTIONS = {
    "onboard_confirm", "config_set", "profile_use", "tools_promote", "tools_remove",
    "tools_import",
    "mcp_add", "mcp_remove", "secret_set", "secret_unset",
}
```

- [ ] **Step 5: Run to verify pass** — `python -m pytest tests/cli/test_extensions_cmd.py -q` (4 tests pass).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/cli/commands/extensions_cmd.py src/gaa/server/actions.py tests/cli/test_extensions_cmd.py
git commit -m "feat(actions): admin management handlers (mcp_add/remove/list, secret_set/unset/list)"
```

### Task 4: Expose management tools as MCP tools

**Files:**
- Modify: `src/gaa/mcp/tools.py:28-68` (`_SPECS`)
- Test: `tests/mcp/test_admin_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/mcp/test_admin_tools.py
from gaa.mcp import tools

MGMT = {"mcp_add", "mcp_remove", "mcp_list", "secret_set", "secret_unset", "secret_list"}


def test_management_tools_listed_only_for_admin():
    admin_names = {t["name"] for t in tools.tool_specs(is_admin=True)}
    user_names = {t["name"] for t in tools.tool_specs(is_admin=False)}
    assert MGMT <= admin_names          # admin sees them
    assert not (MGMT & user_names)      # non-admin sees none


def test_management_tool_schemas_have_required_fields():
    specs = {t["name"]: t for t in tools.tool_specs(is_admin=True)}
    assert specs["mcp_add"]["input_schema"]["required"] == ["name"]
    assert specs["secret_set"]["input_schema"]["required"] == ["name", "value"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/mcp/test_admin_tools.py -q`
Expected: FAIL (specs not present).

- [ ] **Step 3: Implement** — add to `_SPECS` in `src/gaa/mcp/tools.py` (these names are already in `ADMIN_ACTIONS`, so `tool_specs`/`run_tool`'s existing admin filter applies automatically):

```python
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
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/mcp/test_admin_tools.py -q` (2 tests pass).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/mcp/tools.py tests/mcp/test_admin_tools.py
git commit -m "feat(mcp): expose admin management tools (admin-gated)"
```

---

## Phase 3 — render_config profiles + registry merge

> **Spike A/C findings applied** (`docs/spikes/2026-06-16-openclaw-tools-reload.md`): non-admin tool block is `{"allow": ["gaa__*"]}` (absolute allowlist — verified built-ins are blocked); admin **omits** the `tools` key (full suite); both gateways share one persona workspace via `agents.defaults.workspace`. The live re-probe in Task 10 is the final validation.

### Task 5: Per-profile render_config (admin vs nonadmin)

**Files:**
- Modify: `src/gaa/server/openclaw_config.py:9` (signature) and `:41-68` (tool block + MCP env)
- Test: `tests/server/test_config_profiles.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/server/test_config_profiles.py
import json
from gaa.server.openclaw_config import render_config


def test_nonadmin_allowlists_gaa_and_omits_deny():
    cfg = json.loads(render_config(profile="nonadmin"))
    assert "deny" not in cfg.get("tools", {})           # the ineffective blocklist is gone
    assert cfg["tools"]["allow"] == ["gaa__*"]           # verified absolute allowlist (Spike A)
    assert cfg["mcp"]["servers"]["gaa"]["env"]["GAA_MCP_ADMIN"] == "0"
    assert cfg["agents"]["defaults"]["workspace"]         # shared persona workspace (Spike C)


def test_admin_omits_tools_key_and_admin_mcp():
    cfg = json.loads(render_config(profile="admin"))
    assert "tools" not in cfg                             # omitting tools = full built-in suite
    assert cfg["mcp"]["servers"]["gaa"]["env"]["GAA_MCP_ADMIN"] == "1"


def test_default_profile_is_nonadmin():
    assert json.loads(render_config())["tools"]["allow"] == ["gaa__*"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/server/test_config_profiles.py -q`
Expected: FAIL (no `profile` param).

- [ ] **Step 3: Implement** — add `import os` at the top of the module; change the signature and the tool/MCP-env/workspace blocks:

```python
def render_config(*, model: str = "google/gemma-4-31b-it", profile: str = "nonadmin") -> str:
    is_admin = (profile == "admin")
    ...
    # mcp.servers.gaa.env: set GAA_MCP_ADMIN literally per profile (was a ${ENV} ref)
    "GAA_MCP_ADMIN": "1" if is_admin else "0",
    ...
    # Shared persona workspace so BOTH gateways use one persona (Spike C).
    cfg["agents"]["defaults"]["workspace"] = os.environ.get(
        "OPENCLAW_WORKSPACE", "/home/node/.openclaw/workspace")
    # Tool policy (Spike A, docs/spikes/2026-06-16-openclaw-tools-reload.md):
    #   non-admin -> absolute allowlist of ONLY the gaa MCP tools (built-ins blocked)
    #   admin     -> OMIT the tools key entirely -> full built-in suite + gaa tools
    # deny-by-group does NOT restrict; never use it.
    if not is_admin:
        cfg["tools"] = {"allow": ["gaa__*"]}
```

Delete the old trailing `"tools": {"deny": ["group:openclaw"]}` literal; do NOT set a `tools` key for the admin profile.

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/server/test_config_profiles.py -q`.

- [ ] **Step 5: Update the existing config test** — `tests/server/test_openclaw_config.py::test_tools_trimmed_to_mcp_only` asserts the old deny. Replace it:

```python
def test_nonadmin_profile_allowlists_instead_of_denylist():
    cfg = json.loads(render_config(profile="nonadmin"))
    assert cfg["tools"].get("allow") and "deny" not in cfg["tools"]
```

- [ ] **Step 6: Run full config tests** — `python -m pytest tests/server/test_openclaw_config.py tests/server/test_config_profiles.py -q`.

- [ ] **Step 7: Commit**

```bash
git add src/gaa/server/openclaw_config.py tests/server/test_config_profiles.py tests/server/test_openclaw_config.py
git commit -m "feat(config): per-profile render (admin full suite vs non-admin allow-list)"
```

### Task 6: Merge registry servers + inject secrets

**Files:**
- Modify: `src/gaa/server/openclaw_config.py` (after the base `mcp.servers` block)
- Test: `tests/server/test_config_profiles.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_registered_servers_merged_into_both_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.server import extensions
    extensions.set_secret("CRAWLER_KEY", "zzz")
    extensions.add_server(name="crawler", command="npx", args=["x-mcp"], url=None,
                          env={"CRAWLER_KEY": "CRAWLER_KEY"})
    for profile in ("admin", "nonadmin"):
        cfg = json.loads(render_config(profile=profile))
        srv = cfg["mcp"]["servers"]["crawler"]
        assert srv["command"] == "npx" and srv["args"] == ["x-mcp"]
        assert srv["env"]["CRAWLER_KEY"] == "zzz"          # secret injected by value


def test_nonadmin_allowlist_includes_registered_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.server import extensions
    extensions.add_server(name="crawler", command="npx", args=[], url=None, env={})
    cfg = json.loads(render_config(profile="nonadmin"))
    assert "crawler__*" in cfg["tools"]["allow"]           # shared with non-admin (wildcard form)
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/server/test_config_profiles.py -q` (the two new tests FAIL).

- [ ] **Step 3: Implement** — after building the base `cfg["mcp"]["servers"]` dict and the `tools` block, merge the registry:

```python
    from gaa.server import extensions
    secrets = {n: extensions.get_secret(n) for n in extensions.list_secret_names()}
    for s in extensions.list_servers():
        entry = {}
        if s.get("command"):
            entry["command"] = s["command"]
            entry["args"] = s.get("args", [])
        if s.get("url"):
            entry["url"] = s["url"]
        # env maps the server's env var name -> stored secret name; inject the value
        entry["env"] = {k: secrets.get(v, "") for k, v in (s.get("env") or {}).items()}
        cfg["mcp"]["servers"][s["name"]] = entry
        if not is_admin:
            cfg["tools"]["allow"].append(f"{s['name']}__*")   # share registered tools with non-admin
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/server/test_config_profiles.py -q`.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/openclaw_config.py tests/server/test_config_profiles.py
git commit -m "feat(config): merge registered MCP servers + inject secrets into both profiles"
```

---

## Phase 4 — Two gateways, routing, reload

### Task 7: Front-door routing by is_admin

**Files:**
- Modify: `src/gaa/server/openclaw_client.py:42-46` (accept a per-instance URL), `src/gaa/server/app.py:86` (build two clients), `:106-116` (route in `/chat`)
- Test: `tests/server/test_chat_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_chat_routing.py
import os
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_ADMIN_KEY", "secret-admin")
    monkeypatch.setenv("GAA_AGENT_TOKEN", "tok")
    monkeypatch.setenv("OPENCLAW_URL_NONADMIN", "http://nonadmin:1")
    monkeypatch.setenv("OPENCLAW_URL_ADMIN", "http://admin:2")
    from gaa.server.app import create_app
    app = create_app()
    return app


def test_chat_routes_to_admin_url_when_admin(monkeypatch, tmp_path):
    app = _client(monkeypatch, tmp_path)
    seen = {}

    class Fake:
        def __init__(self, url): self.url = url
        def stream_chat(self, **kw):
            seen["url"] = self.url
            yield {"type": "done", "run_id": None}

    app.state.openclaw = Fake("nonadmin")          # existing name = non-admin (keeps old tests working)
    app.state.openclaw_admin = Fake("admin")
    c = TestClient(app)
    c.post("/chat", json={"messages": []},
           headers={"authorization": "Bearer tok", "x-gaa-admin-key": "secret-admin"})
    assert seen["url"] == "admin"
    c.post("/chat", json={"messages": []},
           headers={"authorization": "Bearer tok", "x-gaa-admin-key": "wrong"})
    assert seen["url"] == "nonadmin"
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/server/test_chat_routing.py -q`.

- [ ] **Step 3: Implement** — `openclaw_client.py` already takes `url=`; no change needed beyond constructing two. In `app.py`, keep the existing `app.state.openclaw` as the **non-admin** client (so the existing `/chat` tests that set `app.state.openclaw` keep working) and add an admin one:

```python
    app.state.openclaw = RealOpenClawClient(
        url=os.environ.get("OPENCLAW_URL_NONADMIN") or os.environ.get("OPENCLAW_URL"))
    app.state.openclaw_admin = RealOpenClawClient(
        url=os.environ.get("OPENCLAW_URL_ADMIN") or os.environ.get("OPENCLAW_URL"))
```

In `/chat`, route:

```python
        client = app.state.openclaw_admin if is_admin else app.state.openclaw
        events = client.stream_chat(
            messages=body.get("messages", []), is_admin=is_admin,
            active_run_id=body.get("active_run_id") or None)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/server/test_chat_routing.py tests/server/test_app_routes.py tests/server/test_chat_shim.py -q` (the routing test plus the existing /chat tests all pass).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/app.py tests/server/test_chat_routing.py
git commit -m "feat(frontdoor): route /chat to admin vs non-admin gateway by is_admin"
```

### Task 8: Reload trigger after a management mutation

> **Spike B applied:** OpenClaw supports `openclaw mcp reload` (hot-load a new MCP server, NO gateway restart). The flag-file mechanism below stays — the handler (inside the gaa MCP subprocess) can't drive the gateway directly, so it drops a flag the entrypoint supervisor (Task 9) watches and turns into a `openclaw mcp reload` against each gateway.

**Files:**
- Modify: `src/gaa/server/extensions.py` (add `request_reload`), `src/gaa/cli/commands/extensions_cmd.py` (call it on mutations)
- Test: `tests/server/test_extensions.py`

- [ ] **Step 1: Write the failing test**

```python
def test_request_reload_writes_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.server import extensions as ext
    monkeypatch.setattr(ext, "_dir", lambda: tmp_path)
    ext.request_reload()
    assert (tmp_path / "reload.flag").exists()
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/server/test_extensions.py::test_request_reload_writes_flag -q`.

- [ ] **Step 3: Implement** — add to `extensions.py`:

```python
def reload_flag_path() -> str:
    return str(_dir() / "reload.flag")


def request_reload() -> None:
    """Signal the supervisor to re-render configs and reload the gateways."""
    with open(reload_flag_path(), "w") as f:
        f.write("1")
```

Call it at the end of `cmd_mcp_add`, `cmd_mcp_remove`, `cmd_secret_set`, `cmd_secret_unset` (before `return`):

```python
    extensions.request_reload()
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/server/test_extensions.py tests/cli/test_extensions_cmd.py -q`.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/extensions.py src/gaa/cli/commands/extensions_cmd.py tests/server/test_extensions.py
git commit -m "feat(extensions): request_reload flag on registry/secret mutations"
```

### Task 9: Entrypoint — two gateways + supervised reload

> Implement per **Spikes A/B/C**. This is a shell/ops task; verify by local container smoke (no pytest).

**Files:**
- Modify: `scripts/entrypoint.sh`, `Dockerfile` (env)

- [ ] **Step 1: Add env to `Dockerfile`** (after the existing `ENV` block):

> **Spike A/B/C applied:** `OPENCLAW_CONFIG_DIR` is NOT a real env var in this build — use `OPENCLAW_CONFIG_PATH` (the openclaw.json file) + `OPENCLAW_STATE_DIR` (per-gateway state dir) + `--port`. State dirs MUST be per-gateway (sharing cross-contaminates tool policy). The workspace is shared via `agents.defaults.workspace` (set in render_config, Task 5). Reload uses `openclaw mcp reload` (no restart).

```dockerfile
ENV OPENCLAW_HOME=/home/node/.openclaw \
    OPENCLAW_WORKSPACE=/home/node/.openclaw/workspace \
    OPENCLAW_CONFIG_NONADMIN=/home/node/.openclaw-nonadmin/openclaw.json \
    OPENCLAW_CONFIG_ADMIN=/home/node/.openclaw-admin/openclaw.json \
    OPENCLAW_STATE_NONADMIN=/home/node/.openclaw-nonadmin/state \
    OPENCLAW_STATE_ADMIN=/home/node/.openclaw-admin/state \
    OPENCLAW_URL_NONADMIN=http://127.0.0.1:18789 \
    OPENCLAW_URL_ADMIN=http://127.0.0.1:18790
```

- [ ] **Step 2: Rewrite `scripts/entrypoint.sh`** to: restore once → render both profiles → seed the shared `OPENCLAW_HOME/workspace` persona → launch uvicorn + both gateways → watch the reload flag:

```sh
#!/usr/bin/env sh
set -eu
WS="${OPENCLAW_WORKSPACE:-/home/node/.openclaw/workspace}"
NA_CFG="$OPENCLAW_CONFIG_NONADMIN"; NA_STATE="$OPENCLAW_STATE_NONADMIN"
AD_CFG="$OPENCLAW_CONFIG_ADMIN";    AD_STATE="$OPENCLAW_STATE_ADMIN"
mkdir -p "$WS" "$(dirname "$NA_CFG")" "$NA_STATE" "$(dirname "$AD_CFG")" "$AD_STATE" "$GAA_CACHE_DIR"
python3 -m gaa.persist restore || true

render() {   # $1 = profile, $2 = output openclaw.json file
  python3 -c "import os; from gaa.server.openclaw_config import render_config; \
print(render_config(model=os.environ.get('LLM_MODEL','google/gemma-4-31b-it'), profile='$1'))" > "$2"
}
render nonadmin "$NA_CFG"
render admin    "$AD_CFG"

[ -f "$WS/SOUL.md" ]   || cp /opt/gaa/openclaw/SOUL.md   "$WS/SOUL.md"   2>/dev/null || true
[ -f "$WS/AGENTS.md" ] || cp /opt/gaa/openclaw/AGENTS.md "$WS/AGENTS.md" 2>/dev/null || true
[ -f "$WS/MEMORY.md" ] || cp /opt/gaa/openclaw/MEMORY.md "$WS/MEMORY.md" 2>/dev/null || true
export OPENCLAW_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-}"

python3 -m uvicorn gaa.server.app:app --host 0.0.0.0 --port 8080 &
OPENCLAW_CONFIG_PATH="$NA_CFG" OPENCLAW_STATE_DIR="$NA_STATE" openclaw gateway run --bind lan --port 18789 &
OPENCLAW_CONFIG_PATH="$AD_CFG" OPENCLAW_STATE_DIR="$AD_STATE" openclaw gateway run --bind lan --port 18790 &

# Reload loop (Spike B): on the flag (set by request_reload), re-render both configs
# then HOT-reload each gateway's MCP servers WITHOUT a restart. Confirm the exact
# reload-targeting via `openclaw mcp reload --help` (per-gateway CONFIG_PATH/STATE_DIR
# env as below, or a --port flag).
FLAG="$GAA_CACHE_DIR/extensions/reload.flag"
while true; do
  sleep 3
  if [ -f "$FLAG" ]; then
    rm -f "$FLAG"
    render nonadmin "$NA_CFG"; render admin "$AD_CFG"
    OPENCLAW_CONFIG_PATH="$NA_CFG" OPENCLAW_STATE_DIR="$NA_STATE" openclaw mcp reload || true
    OPENCLAW_CONFIG_PATH="$AD_CFG" OPENCLAW_STATE_DIR="$AD_STATE" openclaw mcp reload || true
  fi
done
```

- [ ] **Step 3: Local smoke** — build the image and confirm both gateways serve and the gaa MCP tools work on each:

```bash
docker buildx build --platform linux/amd64 -t gaa-admin-test:local --load .
docker run --rm -p 8080:8080 --env-file .env.deploy gaa-admin-test:local &
sleep 30
curl -s localhost:8080/health      # {"status":"ok"}
```

- [ ] **Step 4: Commit**

```bash
git add scripts/entrypoint.sh Dockerfile
git commit -m "feat(runtime): two gateways (admin/non-admin) + supervised config reload"
```

---

## Phase 5 — Deploy + live verification

### Task 10: Build, deploy, and re-probe the security boundary

**Files:** none (ops). Uses `.env.deploy`, the deploy quick-ref in the deploy-gotchas notes.

- [ ] **Step 1: Full suite green** — `python -m pytest -q` (all prior + new tests pass).

- [ ] **Step 2: Build + push + deploy** (flavor per Spike C):

```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode-openclaw
TAG="v$(date +%Y%m%d-%H%M%S)"
IMG="vcr.vngcloud.vn/111480-abp111723/gaa-custom-agent:$TAG"
bash /Users/lap16006/.claude/skills/agentbase/scripts/cr.sh credentials docker-login
docker buildx build --platform linux/amd64 -t "$IMG" --push .
bash /Users/lap16006/.claude/skills/agentbase/scripts/runtime.sh update \
  runtime-1628c468-d967-4e78-bae9-f551b7da3e9d --image "$IMG" \
  --flavor runtime-s2-general-2x4 --env-file .env.deploy --from-cr \
  --description "admin runtime extension + non-admin lockdown"
# poll endpoints list until the new version is ACTIVE before testing
```

- [ ] **Step 3: Re-probe the boundary (the regression test for the hole).** Against the public frontend (no admin cookie), ask the agent to list its tools; assert the result contains **only** `gaa__*` (+ any registered) and **none** of `exec`, `read`, `write`, `edit`, `apply_patch`, `file_fetch`, `file_write`, `sessions_spawn`. Then ask it to read `/etc/os-release` and confirm it **refuses/cannot** (no file contents returned).

- [ ] **Step 4: Verify admin power + extension flow.** With the admin passphrase (unlock → cookie), in admin chat: (a) confirm `exec`/`read` are available; (b) `secret_set` a test key then `mcp_add` a trivial MCP server; (c) confirm a reload happens and the new server's tools appear; (d) confirm a **non-admin** turn can now call the new server's tool (shared) but still cannot `exec`.

- [ ] **Step 5: Commit any fixups, then finish the branch** via `superpowers:finishing-a-development-branch`.

---

## Self-Review (against the spec)

- **Spec coverage:** two gateways (Tasks 7, 9) · non-admin allow-list lockdown (Tasks 5, 0.1, 10.3) · admin full suite (Task 5) · registry + secrets (Tasks 1, 3, 4) · vStorage persistence (Task 2) · render merge + secret injection (Task 6) · shared registered tools (Task 6) · chat-driven management tools (Tasks 3, 4) · reload (Tasks 8, 9, 0.2) · routing by is_admin (Task 7) · live re-probe (Task 10). All spec sections map to a task.
- **Spikes gate the unknowns** the spec flagged (allow-list syntax, reload, resources); Phases 3–4 explicitly defer their OpenClaw-specific values to those findings, with the Task 10 re-probe as the real validation.
- **Secret rotation** is intentionally out of scope (owner-deferred), matching the spec.
