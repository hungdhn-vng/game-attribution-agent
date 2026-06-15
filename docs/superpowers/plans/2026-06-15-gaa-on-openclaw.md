# GAA-on-OpenClaw Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-host the GAA agent on a self-hosted OpenClaw runtime packaged into our own Custom AgentBase image — OpenClaw owns the loop/tool-calling/browser/MCP/security; GAA becomes an MCP analysis server + a small HTTP front door that serves the byte-exact dossier and bridges chat.

**Architecture:** One container, one exposed port (`:8080`). A supervisor runs the FastAPI **front door** (`/health`, `/runs/<id>/<artifact>`, `/chat` shim, `/upload`) and the **OpenClaw daemon** (pointed at MaaS via its `openai-completions` provider). OpenClaw spawns the **GAA MCP server** (stdio) which wraps the existing `actions.dispatch` over `gaa.core`. Runs are written to a shared FS and served byte-exact by the front door. Durable state snapshots to vStorage.

**Tech Stack:** Python 3.11 (FastAPI, `mcp` SDK, `jsonschema`, httpx, boto3) reusing all of `gaa.core`; Node 24 (OpenClaw, official Docker image); MaaS LLM (OpenAI-compatible).

**Spec:** `docs/superpowers/specs/2026-06-15-gaa-on-openclaw-design.md` (Spike 1 PASSED — §15).

**Reuse / retire (locked by the spec):**
- **Reuse unchanged:** `gaa.core`, `gaa.runs`, `gaa.config`, `gaa.lab`, `gaa.tools_registry`, `gaa.cli`, `server/actions.py` (the dispatch seam), the `GET /runs/<id>/<artifact>` route logic, `persist.py` (re-targeted).
- **Retire:** `server/agent.py` (homegrown loop), `server/capabilities.py` (exec/browse/self_edit — now OpenClaw's), the loop bits of `server/persona.py` (protocol/tool-guide/system-prompt), and `server/tools.py` (the loop-hardening registry — never used on this branch).

**Conventions:** run tests with `.venv/bin/python -m pytest`. The `.venv` is created locally (`uv venv --python 3.11 .venv && uv pip install -e ".[server]" && uv pip install pytest moto`). Note: uv venvs ship no `pip` — always use `uv pip install`. Baseline suite = **358 passing**. Commit after every green step.

---

## Phase A — Container/integration spikes (resolve the unknowns first)

These are **verification tasks**, not TDD. Each ends by recording concrete findings into a new appendix `## Spike findings (Phase A)` **at the bottom of this plan** — later phases reference them. Do these in a scratch dir (`spikes/phaseA/`), not in `src/`. Creds come from the gitignored `.env` in the sibling repo (`/Users/lap16006/Documents/Projects/TestGreenNode/.env`) — never commit secrets.

### Task A1: OpenClaw runs headless in a container

**Files:** Create `spikes/phaseA/A1-openclaw-docker.md` (findings notes).

- [ ] **Step 1: Pull and run the official OpenClaw image foreground**

Run:
```bash
docker run --rm -e OPENCLAW_GATEWAY_BIND=loopback -p 18789:18789 \
  ghcr.io/openclaw/openclaw:latest 2>&1 | tee /tmp/A1.log
```
Expected: the gateway boots and logs a listening line on `:18789`. (If the image tag differs, resolve it from `docs.openclaw.ai/install/docker` / the repo `docker-compose.yml`.)

- [ ] **Step 2: Confirm reachability from the host**

Run (in another shell): `curl -sS -i http://127.0.0.1:18789/ | head -5`
Expected: an HTTP response (Control UI or a 401/handshake), not connection-refused. If refused, switch `OPENCLAW_GATEWAY_BIND=lan` and retry — this is the known container-bind gotcha (issue #61779).

- [ ] **Step 3: Record findings**

Write to `spikes/phaseA/A1-openclaw-docker.md` and the plan appendix: exact image ref + tag, the working `OPENCLAW_GATEWAY_BIND` value, how to run it foreground (entrypoint/cmd), the config file path inside the container (`~/.openclaw/openclaw.json` vs `/root/.openclaw/...`), and the health/readiness signal (a URL that returns 200 when ready).

### Task A2: OpenClaw → MaaS → MCP stub, end-to-end tool dispatch

**Files:** Create `spikes/phaseA/A2-mcp-stub/` (a 1-tool stub MCP server + `openclaw.json`).

- [ ] **Step 1: Write a trivial stdio MCP server stub**

Create `spikes/phaseA/A2-mcp-stub/echo_server.py` exposing one tool `echo(text: string)` that returns `{"echoed": text}`. (Use the `mcp` SDK low-level `Server` + `stdio_server`; this also validates the SDK install + return shape we'll rely on in Phase B.)

- [ ] **Step 2: Write an `openclaw.json` pointing at MaaS + the stub**

Create `spikes/phaseA/A2-mcp-stub/openclaw.json` (JSON5) — provider `maas` with `api: "openai-completions"`, `baseUrl: "${LLM_BASE_URL}"`, `apiKey: "${LLM_API_KEY}"`, `models: [{id: "minimax/minimax-m2.5", ...}]`; `agents.defaults.model.primary: "maas/minimax/minimax-m2.5"`; `agents.defaults.mcpServers.echo: {command: "python", args: ["/work/echo_server.py"]}`. (MiniMax was fastest in Spike 1; Gemma/Qwen are interchangeable.)

- [ ] **Step 3: Run OpenClaw with this config and ask it to use the tool**

Run OpenClaw in the container with the config + creds mounted, then send (via the Control UI or gateway): *"Use the echo tool to echo the word lobster."*
Expected: OpenClaw calls `echo`, the stub logs the call, and OpenClaw's reply contains `lobster` from the tool result.

- [ ] **Step 4: Record findings**

Append to the plan appendix: the **exact working `openclaw.json` shape** (provider + model + mcpServers keys), the stdio invocation that worked, the chosen model, whether `tool_choice`/`extra_body` tweaks were needed, and the SDK `call_tool` return type the stub used (so Phase B matches it).

### Task A3: Admin-gating mechanism

**Files:** Update `spikes/phaseA/A3-admin.md`.

- [ ] **Step 1: Determine how to gate dangerous tools per OpenClaw's model**

Investigate (docs `gateway/config-tools` + the Control UI): does OpenClaw support per-tool approval/permission gating, and can a tool call receive a caller-supplied flag? Test the simplest viable option: (a) OpenClaw approval prompts for flagged tools, or (b) the front-door shim injects an `is_admin` signal that reaches the MCP `call_tool` (e.g. via a system-context line the MCP server reads, or a dedicated argument).

- [ ] **Step 2: Record the chosen mechanism**

Append to the appendix the decision (approvals vs. injected flag), and exactly how `is_admin` reaches `run_tool` in Phase B. **Default if inconclusive:** the shim sets env/context so the MCP server dispatches admin tools only when an `is_admin` argument is present on the call; non-admin sessions never get the flag. Phase B's `run_tool` already takes `is_admin` explicitly, so only the wiring in `server.py` depends on this.

### Task A4: Dossier coexistence + chat transport/session model

**Files:** Update `spikes/phaseA/A4-transport.md`.

- [ ] **Step 1: Run a static server on :8080 alongside OpenClaw**

In the container, run a throwaway `python -m http.server 8080` (or a 3-line FastAPI) serving a fixture `report.html` while OpenClaw runs on `:18789`. Confirm `curl -sS http://127.0.0.1:8080/report.html` returns the file byte-exact (`cmp` against the source).
Expected: byte-exact; the two processes coexist.

- [ ] **Step 2: Determine how the shim drives one chat turn and streams it**

Find the simplest reliable transport for the front-door shim to: send a user turn to OpenClaw, receive streamed activity/assistant tokens, and know when the turn is done. Check for an HTTP chat/WebChat backend endpoint first; fall back to the gateway WS (operator handshake: `Origin` header, `connect.challenge`, protocol 3, scopes `operator.*`, `auth:{token}`). Also determine the **session model**: does OpenClaw accept a full `messages[]` per turn, or must the shim maintain a session id and send only the latest user message?

- [ ] **Step 3: Record findings**

Append to the appendix: the chat transport (endpoint/WS + auth), the streaming event shape, the session model (stateless-messages vs. session-id), and how a tool result's `run_id` surfaces to the shim. **This determines the concrete `OpenClawClient` in Task C5.**

- [ ] **Step 4: Go/No-Go checkpoint**

If A1–A4 all pass, proceed to Phase B. If A2 (MCP dispatch) or A4 (transport) is unworkable, STOP and reconsider — but Spike 1 + research make these low-risk.

---

## Phase B — GAA MCP server (pure, TDD, no OpenClaw needed)

The core logic lives in a framework-free module (`gaa/mcp/tools.py`) so it is fully unit-testable; a thin SDK adapter (`gaa/mcp/server.py`) wires it to OpenClaw and is validated live (it was exercised by Spike A2).

### Task B1: Add dependencies

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Add `mcp` and `jsonschema` to the server extra**

In `pyproject.toml`, under `[project.optional-dependencies]` `server = [...]`, add `"mcp>=1.2"` and `"jsonschema>=4.0"`.

- [ ] **Step 2: Install and verify import**

Run: `.venv/bin/pip install -e ".[server]" && .venv/bin/python -c "import mcp, jsonschema; from mcp.server import Server; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml && git commit -m "build: add mcp + jsonschema deps for the GAA MCP server"
```

### Task B2: Tool spec table + admin-filtered listing

**Files:** Create `src/gaa/mcp/__init__.py` (empty), `src/gaa/mcp/tools.py`; Test `tests/mcp/test_tool_specs.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/test_tool_specs.py
from gaa.mcp import tools

def test_specs_include_core_analysis_tools():
    names = {t["name"] for t in tools.tool_specs(is_admin=False)}
    assert {"analyze", "segments", "report", "status"} <= names

def test_admin_tools_hidden_from_non_admin():
    non_admin = {t["name"] for t in tools.tool_specs(is_admin=False)}
    admin = {t["name"] for t in tools.tool_specs(is_admin=True)}
    assert "config_set" not in non_admin
    assert "config_set" in admin

def test_every_spec_has_object_schema():
    for t in tools.tool_specs(is_admin=True):
        assert t["input_schema"]["type"] == "object"
        assert "exec" not in t["name"] and "browse" not in t["name"]  # OpenClaw owns those
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/mcp/test_tool_specs.py -v`
Expected: FAIL (`ModuleNotFoundError: gaa.mcp`).

- [ ] **Step 3: Implement `tools.py` spec table + `tool_specs()`**

```python
# src/gaa/mcp/tools.py
"""GAA analysis exposed as MCP tools — framework-free core.

Wraps the existing action seam (gaa.server.actions.dispatch over gaa.core). The
general capabilities (exec/browse/self_edit) are intentionally NOT here — OpenClaw
owns those. Admin-class tools are filtered out of non-admin listings (defense in
depth on top of dispatch's own admin gate)."""
from __future__ import annotations

import json
import jsonschema

from gaa.server import actions

_STR = {"type": "string"}

# name -> (description, input_schema). admin/mutating are read from actions.* sets.
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
}


def all_tool_names() -> list[str]:
    return list(_SPECS)


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
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/mcp/test_tool_specs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/mcp/__init__.py src/gaa/mcp/tools.py tests/mcp/test_tool_specs.py
git commit -m "feat(mcp): GAA tool spec table + admin-filtered listing"
```

### Task B3: `run_tool` — validate args, dispatch, wrap result

**Files:** Modify `src/gaa/mcp/tools.py`; Test `tests/mcp/test_run_tool.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/test_run_tool.py
from gaa.mcp import tools

class FakeCtx: pass

def test_unknown_tool_returns_error():
    r = tools.run_tool(FakeCtx(), "nope", {}, is_admin=True)
    assert r["status"] == "error" and "unknown" in r["error"].lower()

def test_missing_required_arg_rejected_before_dispatch():
    r = tools.run_tool(FakeCtx(), "analyze", {}, is_admin=False)
    assert r["status"] == "error" and "query" in r["error"]

def test_admin_tool_blocked_for_non_admin():
    r = tools.run_tool(FakeCtx(), "config_set", {"key": "k", "value": "v"}, is_admin=False)
    assert r["status"] == "error" and "admin" in r["error"].lower()

def test_valid_call_reaches_dispatch(monkeypatch):
    seen = {}
    def fake_dispatch(ctx, action, args, *, is_admin):
        seen.update(action=action, args=args, is_admin=is_admin)
        return {"status": "success", "run_id": "r-1"}
    monkeypatch.setattr(tools.actions, "dispatch", fake_dispatch)
    r = tools.run_tool(FakeCtx(), "analyze", {"query": "why drop?"}, is_admin=False)
    assert r == {"status": "success", "run_id": "r-1"}
    assert seen == {"action": "analyze", "args": {"query": "why drop?"}, "is_admin": False}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/mcp/test_run_tool.py -v`
Expected: FAIL (`AttributeError: module 'gaa.mcp.tools' has no attribute 'run_tool'`).

- [ ] **Step 3: Implement `run_tool` in `tools.py`**

Append to `src/gaa/mcp/tools.py`:
```python
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
    return actions.dispatch(ctx, name, arguments or {}, is_admin=is_admin)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/mcp/test_run_tool.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/mcp/tools.py tests/mcp/test_run_tool.py
git commit -m "feat(mcp): run_tool — jsonschema validation + admin gate + dispatch"
```

### Task B4: stdio MCP server adapter

**Files:** Create `src/gaa/mcp/server.py`; Test `tests/mcp/test_server_adapter.py`.

> Use the exact `mcp` SDK `call_tool` return shape recorded in Spike A2. The code below uses the common `list[TextContent]` return; adjust if A2 found otherwise.

- [ ] **Step 1: Write the failing test (adapter wiring, no live stdio)**

```python
# tests/mcp/test_server_adapter.py
import json
from gaa.mcp import server

def test_build_server_lists_and_calls(monkeypatch):
    monkeypatch.setattr(server, "build_context", lambda: object())
    monkeypatch.setattr(server.tools, "run_tool",
                        lambda ctx, name, args, *, is_admin: {"status": "success", "echo": args})
    srv, listed, called = server._for_test_handles(is_admin=True)
    names = [t.name for t in listed()]
    assert "analyze" in names
    out = called("analyze", {"query": "x"})
    assert json.loads(out[0].text) == {"status": "success", "echo": {"query": "x"}}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/mcp/test_server_adapter.py -v`
Expected: FAIL (`ModuleNotFoundError`/`AttributeError`).

- [ ] **Step 3: Implement `server.py`**

```python
# src/gaa/mcp/server.py
"""Thin stdio MCP adapter: exposes gaa.mcp.tools over the MCP protocol for OpenClaw.

is_admin source is set by Spike A3's chosen mechanism; default reads GAA_MCP_ADMIN
(the container/shim sets it for admin sessions)."""
from __future__ import annotations

import asyncio
import json
import os

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from gaa.cli.wiring import build_context
from gaa.mcp import tools


def _is_admin() -> bool:
    return os.environ.get("GAA_MCP_ADMIN", "").strip().lower() in ("1", "true", "yes", "on")


def build_server(ctx, *, is_admin: bool) -> Server:
    srv = Server("gaa")

    @srv.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=t["name"], description=t["description"],
                           inputSchema=t["input_schema"]) for t in tools.tool_specs(is_admin=is_admin)]

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = tools.run_tool(ctx, name, arguments or {}, is_admin=is_admin)
        return [types.TextContent(type="text", text=json.dumps(result))]

    return srv


def _for_test_handles(*, is_admin: bool):
    """Expose the registered list/call handlers synchronously for unit tests."""
    ctx = build_context()
    srv = build_server(ctx, is_admin=is_admin)
    loop = asyncio.new_event_loop()
    listed = lambda: loop.run_until_complete(srv.list_tools())
    called = lambda name, args: loop.run_until_complete(srv.call_tool(name, args))
    return srv, listed, called


def main() -> None:
    ctx = build_context()
    srv = build_server(ctx, is_admin=_is_admin())

    async def _run():
        async with stdio_server() as (read, write):
            await srv.run(read, write, srv.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/mcp/test_server_adapter.py -v`
Expected: PASS. (If the SDK exposes handlers differently, align `_for_test_handles` with the SDK's registry per A2.)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/mcp/server.py tests/mcp/test_server_adapter.py
git commit -m "feat(mcp): stdio MCP server adapter delegating to tools.run_tool"
```

---

## Phase C — Front door (trim app.py; add the shim + /upload)

### Task C1: Trim `app.py` to `/health` + `/runs` (drop the homegrown loop)

**Files:** Modify `src/gaa/server/app.py`; Test `tests/server/test_app_routes.py` (existing).

- [ ] **Step 1: Update tests to the new surface**

In `tests/server/test_app_routes.py`, delete/adjust any test that POSTs `/chat` to the in-process `ChatAgent` or `/invocations`. Keep/confirm: `GET /health` → 200; `GET /runs/<id>/report.html` serves a fixture byte-exact; traversal cases still 404. (Run the file first to see what exists: `.venv/bin/python -m pytest tests/server/test_app_routes.py -v`.)

- [ ] **Step 2: Rewrite `app.py` to the trimmed front door**

Replace `src/gaa/server/app.py` with (keeping the proven artifact route + auth helpers; removing `ChatAgent`/`actions`/`persona` loop imports and the `/chat`+`/invocations` bodies — `/chat` and `/upload` are added in C3/C4):
```python
"""FastAPI front door for the GAA-on-OpenClaw Custom Agent (port 8080).

Routes:
  GET  /health                open; 200 iff front door is up (OpenClaw readiness added in Phase E).
  GET  /runs/<id>/<artifact>  open, read-only, allowlisted, traversal-safe (UNCHANGED).
  POST /chat                  Bearer-gated SSE shim to OpenClaw (Task C3).
  POST /upload                Bearer-gated CSV onboarding (Task C4).
On startup: persist.restore(ctx) (best-effort)."""
from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse

from gaa.cli.wiring import build_context
from gaa import persist

_ARTIFACTS = {"report.html", "summary.md", "activity.log", "ledger.jsonl", "job.json"}
_CONTENT_TYPES = {
    "report.html": "text/html", "summary.md": "text/markdown",
    "activity.log": "text/plain", "ledger.jsonl": "application/x-ndjson",
    "job.json": "application/json",
}


def _const_eq(a: str | None, b: str | None) -> bool:
    return bool(a and b and hmac.compare_digest(a, b))


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


def create_app(ctx=None) -> FastAPI:
    state = {"ctx": ctx}

    def get_ctx():
        if state["ctx"] is None:
            state["ctx"] = build_context()
        return state["ctx"]

    def require_token(request: Request):
        if not _const_eq(_bearer(request), os.environ.get("GAA_AGENT_TOKEN")):
            raise HTTPException(status_code=401, detail="missing or invalid agent token")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            persist.restore(get_ctx())
        except Exception:
            pass
        yield

    app = FastAPI(title="GAA Front Door", lifespan=lifespan)
    app.state.get_ctx = get_ctx
    app.state.require_token = require_token

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/runs/{run_id}/{artifact}")
    def artifact(run_id: str, artifact: str):
        if artifact not in _ARTIFACTS:
            raise HTTPException(status_code=404, detail="unknown artifact")
        runs = get_ctx().runs
        runs_root = runs.path_for("__root_probe__").parent.resolve()
        run_dir = runs.path_for(run_id).resolve()
        if run_dir.parent != runs_root:
            raise HTTPException(status_code=404, detail="not found")
        path = (run_dir / artifact).resolve()
        if path.parent != run_dir or not path.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(str(path), media_type=_CONTENT_TYPES[artifact])

    return app


app = create_app()
```

- [ ] **Step 3: Run the route tests**

Run: `.venv/bin/python -m pytest tests/server/test_app_routes.py -v`
Expected: PASS (health + artifact + traversal). Loop/invocations tests are removed.

- [ ] **Step 4: Commit**

```bash
git add src/gaa/server/app.py tests/server/test_app_routes.py
git commit -m "refactor(server): trim app.py to the front door (health + dossier route)"
```

### Task C2: `OpenClawClient` interface + fake

**Files:** Create `src/gaa/server/openclaw_client.py`; Test `tests/server/test_openclaw_fake.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_openclaw_fake.py
from gaa.server.openclaw_client import FakeOpenClawClient

def test_fake_yields_scripted_events():
    c = FakeOpenClawClient([
        {"type": "activity", "text": "analyzing"},
        {"type": "tool_result", "tool": "analyze", "run_id": "run-7"},
        {"type": "token", "text": "Revenue dropped because..."},
        {"type": "done", "run_id": None},
    ])
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "why?"}],
                             is_admin=False, active_run_id=None))
    assert evs[1]["run_id"] == "run-7"
    assert evs[-1]["type"] == "done"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/server/test_openclaw_fake.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the interface + fake**

```python
# src/gaa/server/openclaw_client.py
"""Boundary to the OpenClaw runtime. The concrete client (Task C5) speaks the transport
recorded in Spike A4; the shim (Task C3) and tests depend only on this interface."""
from __future__ import annotations

from typing import Iterator, Protocol


class OpenClawClient(Protocol):
    def stream_chat(self, *, messages: list[dict], is_admin: bool,
                    active_run_id: str | None) -> Iterator[dict]:
        """Yield normalized events:
          {"type": "activity", "text": ...}      progress
          {"type": "thinking", "text": ...}      reasoning (optional)
          {"type": "token", "text": ...}         assistant token
          {"type": "tool_result", "tool": ...,   a tool finished; analyze carries run_id
                                   "run_id": ...}
          {"type": "done", "run_id": <id|None>}  terminal
        """
        ...


class FakeOpenClawClient:
    """Scripted client for tests."""
    def __init__(self, events: list[dict]):
        self._events = events

    def stream_chat(self, *, messages, is_admin, active_run_id) -> Iterator[dict]:
        for ev in self._events:
            yield ev
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/server/test_openclaw_fake.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/openclaw_client.py tests/server/test_openclaw_fake.py
git commit -m "feat(server): OpenClawClient interface + scripted fake"
```

### Task C3: `/chat` SSE shim (with run-id injection)

**Files:** Modify `src/gaa/server/app.py`, create `src/gaa/server/shim.py`; Test `tests/server/test_chat_shim.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_chat_shim.py
import json
from gaa.server.shim import sse_events

def _parse(stream):
    return [json.loads(line[6:]) for line in stream if line.startswith("data: ")]

def test_done_run_id_injected_from_analyze_result():
    events = [
        {"type": "activity", "text": "analyzing"},
        {"type": "tool_result", "tool": "analyze", "run_id": "run-7"},
        {"type": "token", "text": "done"},
        {"type": "done", "run_id": None},
    ]
    out = _parse(sse_events(events))
    assert out[-1] == {"type": "done", "run_id": "run-7"}

def test_done_always_terminal_even_on_empty():
    out = _parse(sse_events([]))
    assert out[-1]["type"] == "done"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/server/test_chat_shim.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `shim.py`**

```python
# src/gaa/server/shim.py
"""Translate OpenClawClient events into the frontend's SSE contract, and inject the
analyze run_id into the terminal `done` event (robust to the model not echoing it)."""
from __future__ import annotations

import json
from typing import Iterable, Iterator


def sse_events(events: Iterable[dict]) -> Iterator[str]:
    latched_run_id = None
    saw_done = False
    for ev in events:
        if ev.get("type") == "tool_result" and ev.get("tool") == "analyze" and ev.get("run_id"):
            latched_run_id = ev["run_id"]
        if ev.get("type") == "done":
            saw_done = True
            ev = {**ev, "run_id": ev.get("run_id") or latched_run_id}
        yield f"data: {json.dumps(ev)}\n\n"
    if not saw_done:  # never end the stream without a terminal event
        yield f"data: {json.dumps({'type': 'done', 'run_id': latched_run_id})}\n\n"
```

- [ ] **Step 4: Wire `/chat` into `app.py`**

In `create_app`, add (the client is injected; default constructed lazily — concrete impl from C5):
```python
    from fastapi.responses import StreamingResponse
    from gaa.server import shim as _shim

    def get_openclaw():
        client = getattr(app.state, "openclaw", None)
        if client is None:
            from gaa.server.openclaw_client import RealOpenClawClient  # Task C5
            client = RealOpenClawClient()
            app.state.openclaw = client
        return client

    @app.post("/chat")
    def chat(request: Request, body: dict):
        require_token(request)
        is_admin = _const_eq(request.headers.get("x-gaa-admin-key"),
                             os.environ.get("GAA_ADMIN_KEY"))
        events = get_openclaw().stream_chat(
            messages=body.get("messages", []), is_admin=is_admin,
            active_run_id=body.get("active_run_id") or None)
        return StreamingResponse(_shim.sse_events(_safe(events)),
                                 media_type="text/event-stream")
```
And add a module-level helper in `app.py` so a client error still terminates the stream:
```python
def _safe(events):
    try:
        yield from events
    except Exception:
        yield {"type": "done", "run_id": None, "error": "internal error"}
```

- [ ] **Step 5: Run shim tests**

Run: `.venv/bin/python -m pytest tests/server/test_chat_shim.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/server/shim.py src/gaa/server/app.py tests/server/test_chat_shim.py
git commit -m "feat(server): /chat SSE shim with analyze run_id injection"
```

### Task C4: `/upload` CSV onboarding route

**Files:** Modify `src/gaa/server/app.py`; Test `tests/server/test_upload.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_upload.py
import io
from fastapi.testclient import TestClient
from gaa.server.app import create_app

def test_upload_requires_token(monkeypatch):
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 401

def test_upload_dispatches_onboard(monkeypatch):
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    import gaa.server.app as appmod
    calls = []
    monkeypatch.setattr(appmod, "_onboard_from_csv",
                        lambda ctx, path: calls.append(path) or {"status": "success", "run_id": "r1"})
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", headers={"Authorization": "Bearer secret"},
                    files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert len(calls) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/server/test_upload.py -v`
Expected: FAIL (no `/upload`).

- [ ] **Step 3: Implement `/upload` + `_onboard_from_csv` in `app.py`**

Add the import `from fastapi import UploadFile, File` and:
```python
def _onboard_from_csv(ctx, path: str) -> dict:
    from gaa.server import actions
    proposed = actions.dispatch(ctx, "onboard_propose", {"csv": path}, is_admin=False)
    if proposed.get("status") != "success":
        return proposed
    return actions.dispatch(ctx, "onboard_confirm", {}, is_admin=False)
```
and inside `create_app`:
```python
    import tempfile
    from fastapi.responses import JSONResponse

    @app.post("/upload")
    async def upload(request: Request, file: UploadFile = File(...)):
        require_token(request)
        data = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(data); path = tmp.name
        return JSONResponse(_onboard_from_csv(get_ctx(), path))
```
(`onboard_confirm` is intentionally not admin-gated — see `actions.py` comment — so a normal frontend user can upload.)

- [ ] **Step 4: Run upload tests**

Run: `.venv/bin/python -m pytest tests/server/test_upload.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/app.py tests/server/test_upload.py
git commit -m "feat(server): /upload CSV onboarding route"
```

### Task C5: Concrete `RealOpenClawClient` (gated on Spike A4)

**Files:** Modify `src/gaa/server/openclaw_client.py`; Test `tests/server/test_openclaw_real.py` (mock transport).

- [ ] **Step 1: Implement `RealOpenClawClient` per the A4 transport finding**

Using the transport + session model recorded in Spike A4, implement `RealOpenClawClient.stream_chat` to (a) authenticate to OpenClaw with the gateway token from env `OPENCLAW_TOKEN`, (b) send the turn (full `messages[]` if stateless, else map `active_run_id`/conversation to a session id), (c) translate OpenClaw's streamed frames into the normalized events of the `OpenClawClient` interface — emitting a `tool_result` with `run_id` when the `analyze` MCP tool returns, and a terminal `done`. Read `OPENCLAW_URL`/`OPENCLAW_TOKEN` from env.

- [ ] **Step 2: Write a transport-mocked test**

Mock the HTTP/WS layer (per A4) to feed a canned OpenClaw frame sequence and assert `stream_chat` yields the normalized events (incl. `tool_result.run_id` and terminal `done`). Keep the network mocked — no live OpenClaw in unit tests.

- [ ] **Step 3: Run + commit**

Run: `.venv/bin/python -m pytest tests/server/test_openclaw_real.py -v` (PASS), then:
```bash
git add src/gaa/server/openclaw_client.py tests/server/test_openclaw_real.py
git commit -m "feat(server): RealOpenClawClient over the A4 transport"
```

---

## Phase D — OpenClaw workspace (config + persona + red-lines)

### Task D1: `openclaw.json` template + render

**Files:** Create `openclaw/openclaw.json.tmpl`, `src/gaa/server/openclaw_config.py`; Test `tests/server/test_openclaw_config.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_openclaw_config.py
import json
from gaa.server.openclaw_config import render_config

def test_render_wires_maas_provider_and_mcp():
    cfg = json.loads(render_config(model="minimax/minimax-m2.5"))
    prov = cfg["models"]["providers"]["maas"]
    assert prov["api"] == "openai-completions"
    assert prov["baseUrl"] == "${LLM_BASE_URL}" and prov["apiKey"] == "${LLM_API_KEY}"
    assert cfg["agents"]["defaults"]["model"]["primary"] == "maas/minimax/minimax-m2.5"
    assert "gaa" in cfg["agents"]["defaults"]["mcpServers"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/server/test_openclaw_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `render_config`** (shape confirmed by Spike A2)

```python
# src/gaa/server/openclaw_config.py
"""Render OpenClaw's openclaw.json wiring MaaS + the GAA MCP server. Secrets stay as
${ENV} refs (OpenClaw substitutes at load). Shape per Spike A2."""
from __future__ import annotations
import json, os


def render_config(*, model: str = "google/gemma-4-31b-it") -> str:
    cfg = {
        "agents": {"defaults": {
            "model": {"primary": f"maas/{model}"},
            "mcpServers": {"gaa": {
                "command": "python",
                "args": ["-m", "gaa.mcp.server"],
                "env": {"GAA_MCP_ADMIN": "${GAA_MCP_ADMIN}"},
            }},
        }},
        "models": {"providers": {"maas": {
            "api": "openai-completions",
            "baseUrl": "${LLM_BASE_URL}",
            "apiKey": "${LLM_API_KEY}",
            "models": [{"id": model, "name": model, "reasoning": False,
                        "input": ["text"], "contextWindow": 128000, "maxTokens": 8192}],
        }}},
        "gateway": {"bind": os.environ.get("OPENCLAW_GATEWAY_BIND", "loopback")},
    }
    return json.dumps(cfg, indent=2)
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/server/test_openclaw_config.py -v` (PASS), then:
```bash
git add src/gaa/server/openclaw_config.py tests/server/test_openclaw_config.py
git commit -m "feat(server): render openclaw.json (MaaS provider + GAA MCP server)"
```

### Task D2: Persona + red-lines seed for OpenClaw

**Files:** Create `openclaw/SOUL.md`, `openclaw/MEMORY.md`, `openclaw/AGENTS.md`.

- [ ] **Step 1: Author the seeds**

Port the existing persona from `src/gaa/data/seed/SOUL.md` into `openclaw/SOUL.md` (OpenClaw's persona file). Create an near-empty `openclaw/MEMORY.md`. Write `openclaw/AGENTS.md` with the GAA red-lines from `persona.py::_REDLINES` plus: "For any question about a game's metrics/revenue/retention, use the `gaa` MCP analysis tools; reuse the active run for drilldowns; never invent numbers." (These instruct OpenClaw to use the MCP tools.)

- [ ] **Step 2: Commit**

```bash
git add openclaw/SOUL.md openclaw/MEMORY.md openclaw/AGENTS.md
git commit -m "feat(openclaw): seed persona + GAA red-lines for the OpenClaw workspace"
```

---

## Phase E — Container packaging

### Task E1: Supervisor entrypoint

**Files:** Create `scripts/entrypoint.sh`.

- [ ] **Step 1: Write the entrypoint**

```bash
#!/usr/bin/env sh
set -eu
# Render OpenClaw config into the workspace, seed persona on first boot, then run
# the front door (background) and OpenClaw (foreground). tini is PID 1 (see Dockerfile).
mkdir -p "$OPENCLAW_HOME"
python -m gaa.server.openclaw_config_render > "$OPENCLAW_HOME/openclaw.json"
for f in SOUL.md MEMORY.md AGENTS.md; do
  [ -f "$OPENCLAW_HOME/$f" ] || cp "/app/openclaw/$f" "$OPENCLAW_HOME/$f"
done
uvicorn gaa.server.app:app --host 0.0.0.0 --port 8080 &
exec openclaw gateway --config "$OPENCLAW_HOME/openclaw.json"
```
Add a tiny CLI shim `src/gaa/server/openclaw_config_render.py` (`if __name__=="__main__": print(render_config(model=os.environ.get("LLM_MODEL","google/gemma-4-31b-it")))`). Confirm the exact `openclaw` run command + config flag against Spike A1.

- [ ] **Step 2: Commit**

```bash
chmod +x scripts/entrypoint.sh
git add scripts/entrypoint.sh src/gaa/server/openclaw_config_render.py
git commit -m "feat(container): supervisor entrypoint (front door + OpenClaw)"
```

### Task E2: Dockerfile (Node OpenClaw + Python GAA)

**Files:** Modify `Dockerfile`.

- [ ] **Step 1: Write the multi-stage Dockerfile**

Base on the official OpenClaw image (which already has Node 24 + OpenClaw) and add Python + GAA, OR base on `node:24-bookworm-slim` and install both. Concrete (confirm OpenClaw install method from Spike A1):
```dockerfile
FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv tini \
    && rm -rf /var/lib/apt/lists/*
# OpenClaw (install method per Spike A1 — global npm or the official image's binary)
RUN npm install -g @openclaw/openclaw    # confirm package name in A1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY openclaw ./openclaw
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
RUN python3 -m pip install --break-system-packages -e ".[server]"
ENV OPENCLAW_HOME=/root/.openclaw OPENCLAW_GATEWAY_BIND=loopback
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "/app/scripts/entrypoint.sh"]
```

- [ ] **Step 2: Build**

Run: `docker build -t gaa-openclaw:dev .`
Expected: builds clean. Fix any dep/install issues surfaced.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(container): Dockerfile bundling OpenClaw (Node) + GAA (Python)"
```

### Task E3: Local run + health + dossier smoke

**Files:** none (verification).

- [ ] **Step 1: Run with creds**

Run:
```bash
docker run --rm -p 8080:8080 --env-file /Users/lap16006/Documents/Projects/TestGreenNode/.env \
  -e GAA_AGENT_TOKEN=dev -e LLM_MODEL=minimax/minimax-m2.5 gaa-openclaw:dev
```

- [ ] **Step 2: Verify health + a chat→dossier round-trip**

Run: `curl -sS http://127.0.0.1:8080/health` → `{"status":"ok"}`. Then POST `/chat` (Bearer dev) with a "why did my game's revenue drop?" message; confirm SSE streams and a `done.run_id` arrives; then `GET /runs/<id>/report.html` returns the dossier. (This is the first end-to-end proof of the whole architecture.) Record any gaps; fix in the relevant phase.

- [ ] **Step 3: Make `/health` reflect OpenClaw readiness**

Update `app.py::health` to also probe the OpenClaw gateway (per A1's readiness URL) and return 503 until OpenClaw answers; add a test with the probe mocked. Commit:
```bash
git add src/gaa/server/app.py tests/server/test_app_routes.py
git commit -m "feat(server): /health gates on OpenClaw readiness"
```

---

## Phase F — Persistence retarget

### Task F1: Snapshot the OpenClaw workspace subset

**Files:** Modify `src/gaa/persist.py`; Test `tests/test_persist.py` (existing).

- [ ] **Step 1: Update the durable-items test**

In `tests/test_persist.py`, change the expected arcnames: drop `persona` (GAA's old persona dir), add `openclaw` (the OpenClaw workspace durable subset: `openclaw.json`, `SOUL.md`, `MEMORY.md`, `AGENTS.md`). Keep `config.toml`, `profiles.sqlite`, `metrics`, `tools`. Assert a snapshot/restore round-trip via the existing stub-S3/moto fixture.

- [ ] **Step 2: Update `_durable_items`**

Replace the `persona` entry and drop the `persona` import:
```python
def _durable_items(ctx):
    cache = Path(ctx.settings.cache_dir)
    tools = Path(os.environ.get("GAA_TOOLS_DIR", str(cache / "tools")))
    openclaw_home = Path(os.environ.get("OPENCLAW_HOME", str(Path.home() / ".openclaw")))
    return [
        ("config.toml", Path(ctx.config._path), False),
        ("profiles.sqlite", Path(ctx.settings.db_path), False),
        ("metrics", cache / "metrics", True),
        ("tools", tools, True),
        ("openclaw", openclaw_home, True),   # OpenClaw's config + SOUL/MEMORY/AGENTS (its "files are memory")
    ]
```
(Remove `from gaa.server import persona` at the top of the file.)

- [ ] **Step 3: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_persist.py -v` (PASS), then:
```bash
git add src/gaa/persist.py tests/test_persist.py
git commit -m "refactor(persist): snapshot the OpenClaw workspace instead of the old GAA persona dir"
```

---

## Phase G — Retire the homegrown loop

### Task G1: Delete `agent.py`, `capabilities.py`, `tools.py` (+ their tests)

**Files:** Delete `src/gaa/server/agent.py`, `src/gaa/server/capabilities.py`, `src/gaa/server/tools.py`, and their test files.

- [ ] **Step 1: Find dependents**

Run: `grep -rn "server.agent\|server.capabilities\|server import agent\|server import capabilities\|server.tools" src tests` and list every reference.

- [ ] **Step 2: Delete the modules + tests, remove references**

`git rm` the three modules and any `tests/server/test_agent*.py`, `tests/server/test_capabilities*.py`, `tests/server/test_tools*.py`. Remove the now-dead `capabilities` import line from anywhere it appears (it was in the old `app.py`, already gone in C1).

- [ ] **Step 3: Verify the full suite is green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (no import errors; the analysis/core suite + the new mcp/server tests). Fix any straggler imports.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(server): retire the homegrown chat loop (OpenClaw is the loop now)"
```

### Task G2: Reduce `persona.py` to persona files only (or delete)

**Files:** Modify or delete `src/gaa/server/persona.py`.

- [ ] **Step 1: Decide based on remaining references**

After G1, `persist.py` no longer imports `persona`. Run `grep -rn "server.persona\|server import persona" src tests`. If nothing remains, `git rm src/gaa/server/persona.py` and any `tests/server/test_persona*.py`. If something still uses persona file I/O, strip the loop-only members (`_PROTOCOL`, `_ANALYSIS_TOOLS`, `_ADMIN_TOOLS`, `_STANDARD_SESSION`, `_THOUGHT_HINT`, `assemble_system_prompt`, `reasoning_enabled`) and keep only file load/seed if still needed.

- [ ] **Step 2: Verify + commit**

Run: `.venv/bin/python -m pytest -q` (PASS), then:
```bash
git add -A
git commit -m "chore(server): drop the homegrown system-prompt/persona-loop code"
```

---

## Phase H — Deploy to AgentBase + live verification

### Task H1: Build + push the image

- [ ] **Step 1:** Build `linux/amd64` and push to the managed registry:
```bash
docker buildx build --platform linux/amd64 -t vcr.vngcloud.vn/111480-abp111723/gaa:openclaw . --push
```
(Authenticate to the registry first per the `agentbase-deploy` skill.)

### Task H2: Create the Custom Agent runtime

- [ ] **Step 1:** Use the `agentbase-deploy` skill to create a Custom Agent runtime from the image, flavor sized for Node+Python+analytics (≥ `runtime-s2-general-2x4`; size up if A1/E2 showed memory pressure), PUBLIC, 1 replica.
- [ ] **Step 2:** Set runtime env: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (the model chosen from the implementation bake-off), `PERPLEXITY_API_KEY`, `GAA_BENCHMARK_MODE`, `GAA_AGENT_TOKEN`, `GAA_ADMIN_KEY`, `OPENCLAW_TOKEN` (capture from any gateway init), `OPENCLAW_HOME`, `VSTORAGE_*`. Capture the public URL.

### Task H3: Live verification checklist

- [ ] `GET /health` → 200 (only after OpenClaw is ready); runtime ACTIVE.
- [ ] `POST /chat` (Bearer) "why did <game> revenue drop?" → SSE activity + tokens + `done.run_id`.
- [ ] `GET /runs/<id>/report.html` → full dossier byte-exact.
- [ ] A follow-up drilldown reuses the run (`active_run_id`).
- [ ] `POST /upload` a CSV → onboarding succeeds.
- [ ] An admin-gated tool (`config_set`) is refused for a non-admin session and allowed for admin (per A3).
- [ ] A `self_edit`/MEMORY change via OpenClaw survives a redeploy (vStorage restore on boot).
- [ ] Synthesis output is schema-valid `AttributionHypothesis` for the deploy model (else set synthesis model back to the verified Qwen path via config — spec §8).

---

## Phase I — Frontend rewire (follow-on; separate repo `gaa-test-frontend`/`frontend`)

Small, written as its own short plan once the backend is live. Key changes only:
- Point the chat call at the new Custom Agent `POST /chat` URL (contract preserved by the shim — `messages[]` → SSE, then fetch `/runs/<id>/report.html`).
- Change CSV onboarding from the old `POST /invocations` to `POST /upload` (multipart).
- Keep the server-side token injection (Next.js route handler holds `GAA_AGENT_TOKEN`); confirm `done.run_id` drives the dossier-iframe pane.

---

## Self-review

**Spec coverage:** §3 topology → Phases C/E; §4A OpenClaw → A1/D1/E2; §4B MCP server → B; §4C front door → C1/C3/C4; §4D persona → D2; §4E persistence → F; §5 data flow → C3 (marker injection) + E3 (round-trip); §6 frontend → I; §7 security → C3 (token), A3 (admin), C1 (open artifact route); §8 models → A2 + H3 (synthesis re-verify); §9 spikes → Phase A; §10 reuse/retire → B (reuse actions) + G (retire); §11 testing → tests in B/C/D/F. Covered.

**Placeholder scan:** spike-dependent bits (A3 admin mechanism, A4 transport → C5, A1 OpenClaw run command, A2 config/SDK shape) are explicitly **recorded by a Phase-A task and referenced**, with concrete defaults provided — not silent TODOs.

**Type consistency:** `actions.dispatch(ctx, action, args, *, is_admin)` used identically in B3/C4; `tools.run_tool(ctx, name, arguments, *, is_admin)` and `tool_specs(*, is_admin)` consistent across B/C; `OpenClawClient.stream_chat(*, messages, is_admin, active_run_id)` consistent across C2/C3/C5; event shapes (`tool_result.run_id`, terminal `done.run_id`) consistent across C2/C3/shim.

**Note:** Phase A must run before B–H lock their spike-dependent details (C5 transport, server.py admin wiring, Dockerfile OpenClaw install, openclaw.json/SDK shapes). The TDD core (B, C1–C4, D1, F) is spike-independent and can proceed in parallel with A.
