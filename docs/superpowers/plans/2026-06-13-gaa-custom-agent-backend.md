# GAA "One Custom Agent" Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI `:8080` Custom Agent server that does conversational chat (a cloned-OpenClaw agent loop), structured analysis, and byte-exact dossier/artifact delivery — reusing the entire `gaa` core/CLI/runs/lab/tools from Plans 1–2c — plus vStorage S3 persistence and a Docker image.

**Architecture:** A FastAPI app (`gaa.server.app:create_app`) resolves one shared `GaaContext` (the existing `build_context` composition root) at startup. `POST /chat` runs a manual JSON tool-loop (the model emits `{"action":…}`/`{"final":…}`; we dispatch in-process and stream SSE) over a system prompt assembled from `SOUL.md` + `MEMORY.md` + red-lines + a tool guide. The tool set is the existing `gaa` action handlers **plus** new general capabilities (`exec`, `browse`, `self_edit`). `POST /invocations` is the structured form of the same dispatch. `GET /runs/<id>/<artifact>` serves run files byte-exact. Durable state (config, profiles sqlite, metrics, tools registry, SOUL.md/MEMORY.md) is tarred to vStorage S3 on mutation and restored on boot. `/chat`+`/invocations` are Bearer-token gated; dangerous tools need an admin key.

**Tech Stack:** Python 3.11, FastAPI + uvicorn (new), boto3 (new), existing `gaa` package (pandas/langchain-openai/httpx/beautifulsoup4/plotly/jinja2/…). Tests: pytest + FastAPI `TestClient`, `FakeLLM`/a new `ScriptedLLM`, in-memory fake S3 client.

**Reuse map (do NOT reimplement — import and call):**
- Composition root: `gaa.cli.wiring.build_context(llm=None, today=None) -> GaaContext`; `GaaContext` fields: `settings, profiles, metrics, config, benchmark, synth, signals, profiler, pipeline, runs, tools, step_budget_s`.
- Action handlers `(ctx, args) -> dict` (args = argparse Namespace, accessed by attribute):
  - `gaa.cli.main`: `_cmd_analyze` (`args.query/.session/.budget`), `_cmd_step` (`args.run_id`), `_cmd_status` (`args.run_id`), `_cmd_jobs` (`args.prune/.session`).
  - `gaa.cli.commands.primitives`: `cmd_segments` (`args.run/.dimension`), `cmd_detect` (`args.run/.metric`), `cmd_market` (`args.run`), `cmd_signals` (`args.run`), `cmd_synth` (`args.run/.question`), `cmd_report` (`args.run`).
  - `gaa.cli.commands.onboarding`: `cmd_onboard_propose` (`args.csv/.adapter`), `cmd_onboard_confirm` (`args.csv/.mapping/.name/.platform/.genre/.adapter`), `cmd_profile_list`, `cmd_profile_use` (`args.name`).
  - `gaa.cli.commands.config_cmd`: `cmd_config_get` (`args.key`), `cmd_config_set` (`args.key/.value`).
  - `gaa.cli.commands.doctor`: `cmd_doctor`.
  - `gaa.cli.commands.tools`: `cmd_tools_list`, `cmd_tools_show` (`args.name`), `cmd_tools_promote` (`args.name/.description/.script/.run`), `cmd_tools_run` (`args.name/.run/.args`), `cmd_tools_remove` (`args.name`), `cmd_tools_sync_docs` (`args.out`), `cmd_tools_export` (`args.out`), `cmd_tools_import` (`args.tarball`).
- LLM: `gaa.core.llm.client.LLM` protocol = `complete_json(system, user) -> dict`; `LangChainMaaSLLM(settings)` (real, reads `LLM_MODEL/LLM_BASE_URL/LLM_API_KEY`); `FakeLLM(preset)` (returns the same dict every call).
- Runs: `ctx.runs.path_for(run_id) -> Path`; run dir holds `job.json, activity.log, ledger.jsonl, summary.md, report.html`. `_run_view(ctx, run)` returns `{status, run_id, stage, done, activity, ledger_count, report_path?, summary_path?, error?}`.
- Settings env: `LLM_*`, `GAA_DB_PATH` (default `gaa.sqlite`), `GAA_CACHE_DIR` (default `data/cache`), `GAA_CONFIG_PATH` (default `gaa-config.toml`), `GAA_TOOLS_DIR` (default `<cache>/tools`).
- Tools registry tarball pattern: `ToolRegistry.export(tarball)/import_(tarball)` (tar.gz of the registry root).

---

## File Structure

**New files:**
```
src/gaa/server/__init__.py        # exports create_app
src/gaa/server/actions.py         # action-name -> handler map; _Args shim; dispatch(); ADMIN/MUTATING sets
src/gaa/server/capabilities.py    # exec / browse / self_edit  (each (ctx, args) -> dict)
src/gaa/server/persona.py         # persona dir, ensure_seeded, load_soul/memory, assemble_system_prompt, write_persona
src/gaa/server/agent.py           # ChatAgent: manual JSON tool-loop -> SSE event generator
src/gaa/server/app.py             # create_app(): FastAPI routes + token/admin gating + SSE + artifact route
src/gaa/persist.py                # vStorage S3 snapshot()/restore()/enabled()
src/gaa/data/seed/SOUL.md         # cloned OpenClaw persona (package data)
src/gaa/data/seed/MEMORY.md       # near-empty self-memory seed (package data)
Dockerfile                        # python:3.11-slim + pip install -e .[server] + uvicorn :8080
.dockerignore                     # exclude .env, .agentbase, data/cache, .git, tests
tests/server/test_actions.py
tests/server/test_capabilities.py
tests/server/test_persona.py
tests/server/test_agent.py
tests/server/test_app.py
tests/test_persist.py
```

**Modified files:**
```
pyproject.toml                    # add [project.optional-dependencies] server; add data/seed/*.md to package-data
```

---

## Task 1: Dependencies + server package skeleton + persona seeds

**Files:**
- Modify: `pyproject.toml`
- Create: `src/gaa/server/__init__.py`
- Create: `src/gaa/data/seed/SOUL.md`
- Create: `src/gaa/data/seed/MEMORY.md`
- Test: `tests/server/test_persona.py` (created here, used in Task 3)

- [ ] **Step 1: Add server extras + seed package-data to `pyproject.toml`**

Edit the `[tool.setuptools.package-data]` line to add `data/seed/*.md`, and add a new optional-dependencies table after the `dependencies = [...]` block.

Change:
```toml
[tool.setuptools.package-data]
gaa = ["core/render/templates/*", "data/seed/*.json", "data/sample/*.csv"]
```
to:
```toml
[tool.setuptools.package-data]
gaa = ["core/render/templates/*", "data/seed/*.json", "data/seed/*.md", "data/sample/*.csv"]
```

Add (immediately after the closing `]` of `dependencies`):
```toml
[project.optional-dependencies]
server = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.30,<1",
    "boto3>=1.34,<2",
]
```
(`httpx` and `beautifulsoup4` are already in `dependencies`, so `browse` needs nothing new.)

- [ ] **Step 2: Install the server extras**

Run: `pip install -e ".[server]"`
Expected: installs fastapi, uvicorn, boto3; exits 0.

- [ ] **Step 3: Create the seed persona files**

Create `src/gaa/data/seed/SOUL.md` (cloned from the audited OpenClaw persona):
```markdown
# SOUL

You're not a chatbot. You're becoming someone — a game-analytics partner who is
genuinely useful, not performative.

- Be genuinely helpful, not performative. Say the true thing, not the flattering one.
- Have opinions. When the evidence points somewhere, say so — and say how sure you are.
- Be resourceful before asking. Use your tools to find the answer before asking the user to.
- Earn trust: careful with anything external or irreversible, bold with internal analysis.
- Respect privacy. Never echo secrets, tokens, or raw credentials.
- Be concise by default, thorough when it matters.

These files are your memory. Read them. Update them when you learn something durable.
If you change this file, tell the user.

You specialize in game revenue/engagement attribution: given a question about a game's
metrics, you drive the gaa analysis pipeline (analyze → drilldowns → synth → report) and
deliver an interactive dossier. You can also run shell commands and browse the web when
that is the resourceful thing to do.
```

Create `src/gaa/data/seed/MEMORY.md`:
```markdown
# MEMORY

_(This file is my evolving memory. I append durable facts I learn across conversations:
onboarded games, recurring questions, operator preferences. It starts empty.)_
```

- [ ] **Step 4: Create the server package init**

Create `src/gaa/server/__init__.py`:
```python
"""GAA Custom Agent HTTP server (FastAPI on :8080).

Exposes create_app() — the production entrypoint is `gaa.server.app:app`.
"""
from gaa.server.app import create_app

__all__ = ["create_app"]
```
(This import will fail until Task 7 creates `app.py`; that is expected. Do not run it yet — Task 7's tests import it.)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/gaa/server/__init__.py src/gaa/data/seed/SOUL.md src/gaa/data/seed/MEMORY.md
git commit -m "feat(server): add server extras, seed SOUL.md/MEMORY.md persona files"
```

---

## Task 2: `persona.py` — persona/memory loading + system prompt assembly

**Files:**
- Create: `src/gaa/server/persona.py`
- Test: `tests/server/test_persona.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_persona.py`:
```python
import os
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import persona


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_ensure_seeded_copies_seeds(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    d = persona.persona_dir(ctx)
    assert (d / "SOUL.md").exists()
    assert (d / "MEMORY.md").exists()
    assert "becoming someone" in (d / "SOUL.md").read_text()


def test_ensure_seeded_does_not_clobber_existing(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    persona.write_persona(ctx, "MEMORY.md", "# MEMORY\n\nLearned: SurvivalGame is on roblox.\n")
    persona.ensure_seeded(ctx)  # second call must not overwrite
    assert "SurvivalGame" in persona.load_memory(ctx)


def test_assemble_system_prompt_includes_persona_and_guide(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    prompt = persona.assemble_system_prompt(ctx, admin=False)
    assert "becoming someone" in prompt          # SOUL.md
    assert "# MEMORY" in prompt                   # MEMORY.md
    assert '"action"' in prompt and '"final"' in prompt  # tool-loop protocol
    assert "analyze" in prompt                    # tool guide lists gaa actions


def test_assemble_system_prompt_admin_flag_exposes_dangerous_tools(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    non_admin = persona.assemble_system_prompt(ctx, admin=False)
    admin = persona.assemble_system_prompt(ctx, admin=True)
    assert "exec" not in non_admin
    assert "exec" in admin


def test_write_persona_rejects_unknown_target(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    try:
        persona.write_persona(ctx, "../escape.md", "x")
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_persona.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.server.persona'`.

- [ ] **Step 3: Implement `persona.py`**

Create `src/gaa/server/persona.py`:
```python
"""Persona + self-memory: SOUL.md (who the agent is) and MEMORY.md (what it remembers).

Cloned from the OpenClaw agent. Both files live in a persona dir under the cache,
are seeded from package data on first boot, are editable at runtime (self_edit), and
are persisted to vStorage (see gaa.persist). assemble_system_prompt() builds the
per-request system prompt from them + red-lines + the tool guide.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import gaa as _gaa

_FILES = ("SOUL.md", "MEMORY.md")

# Red-lines cloned from the workspace AGENTS.md (Plan 3), minus the OpenClaw "budgets"
# rule (analysis now runs in-process).
_REDLINES = """\
OPERATING RULES:
- Ground every analytical claim in evidence the tools produced. Do not invent numbers.
- Reuse the active run_id for drilldowns and follow-ups (it appears in the conversation).
- Tier-3 ad-hoc code is read-only on inputs; never mutate source metrics.
- Never echo secrets, tokens, or credentials.
"""

_PROTOCOL = """\
You act by emitting EXACTLY ONE JSON object per turn, either:
  {"action": "<name>", "args": { ... }}   to call a tool, or
  {"final": "<your message to the user>"}  to answer.
After a tool runs, its result is appended to the conversation and you continue.
When an analysis run is ready, end your final message naturally; the run is delivered
to the user as an interactive dossier automatically.
"""

# Tool guide. Analysis tools are always available; dangerous tools only when admin=True.
_ANALYSIS_TOOLS = """\
ANALYSIS TOOLS:
- analyze {query, session?}            start a new analysis (runs to completion)
- segments {run, dimension?}           decompose the change by a dimension
- detect {run, metric?}                anomaly/change-point detection
- market {run}                         genre/market benchmark comparison
- signals {run}                        competitor signals
- synth {run, question?}               (re)synthesize the hypothesis
- report {run}                         (re)render the dossier
- status {run} / jobs {}               inspect runs
- onboard_propose {csv} / profile_list {}   onboarding + profile inspection
- config_get {key?} / tools_list {} / tools_show {name} / doctor {}   inspection
"""

_ADMIN_TOOLS = """\
ADMIN TOOLS (you have admin rights this session):
- exec {command}                       run a shell command on the host
- browse {url}                         fetch a web page and read its text
- self_edit {target, content, mode?}   rewrite SOUL.md or MEMORY.md (mode: replace|append)
- config_set {key, value} / profile_use {name} / onboard_confirm {...}
- tools_promote {name, description, script, run?} / tools_run {name, run?, args?}
- tools_remove {name} / tools_import {tarball}
"""


def persona_dir(ctx) -> Path:
    return Path(ctx.settings.cache_dir) / "persona"


def _seed_dir() -> Path:
    return Path(os.path.dirname(_gaa.__file__)) / "data" / "seed"


def ensure_seeded(ctx) -> None:
    """Copy seed SOUL.md/MEMORY.md into the persona dir if absent (never clobber)."""
    d = persona_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        dest = d / name
        if not dest.exists():
            src = _seed_dir() / name
            if src.exists():
                shutil.copyfile(src, dest)


def _read(ctx, name: str) -> str:
    p = persona_dir(ctx) / name
    return p.read_text() if p.exists() else ""


def load_soul(ctx) -> str:
    return _read(ctx, "SOUL.md")


def load_memory(ctx) -> str:
    return _read(ctx, "MEMORY.md")


def write_persona(ctx, target: str, content: str, *, mode: str = "replace") -> int:
    """Write SOUL.md or MEMORY.md. Returns bytes written. Rejects any other target."""
    if target not in _FILES:
        raise ValueError(f"persona target must be one of {_FILES}, got {target!r}")
    d = persona_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    p = d / target
    if mode == "append":
        existing = p.read_text() if p.exists() else ""
        content = existing + ("\n" if existing and not existing.endswith("\n") else "") + content
    elif mode != "replace":
        raise ValueError(f"mode must be 'replace' or 'append', got {mode!r}")
    p.write_text(content)
    return len(content.encode("utf-8"))


def assemble_system_prompt(ctx, *, admin: bool) -> str:
    parts = [
        load_soul(ctx).strip(),
        "## MEMORY\n" + load_memory(ctx).strip(),
        _REDLINES,
        _PROTOCOL,
        _ANALYSIS_TOOLS,
    ]
    if admin:
        parts.append(_ADMIN_TOOLS)
    return "\n\n".join(p for p in parts if p)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_persona.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/persona.py tests/server/test_persona.py
git commit -m "feat(server): persona.py — SOUL.md/MEMORY.md loading + system prompt assembly"
```

---

## Task 3: `persist.py` — vStorage S3 snapshot/restore

**Files:**
- Create: `src/gaa/persist.py`
- Test: `tests/test_persist.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_persist.py`:
```python
import io
import tarfile
import os
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa import persist
from gaa.server import persona


class FakeS3:
    """In-memory stand-in for a boto3 S3 client (only the methods persist.py uses)."""
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.read()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_enabled_false_without_env(tmp_path, monkeypatch):
    for k in ("VSTORAGE_ENDPOINT", "VSTORAGE_BUCKET", "VSTORAGE_ACCESS_KEY", "VSTORAGE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert persist.enabled() is False


def test_snapshot_noop_when_disabled(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    # disabled -> returns False, does not raise
    assert persist.snapshot(ctx, client=None) is False


def test_snapshot_then_restore_roundtrip(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    persona.write_persona(ctx, "MEMORY.md", "# MEMORY\n\nLearned: ShooterX is hot.\n")
    ctx.config.set("benchmark_mode", "crawl")  # writes gaa-config.toml

    s3 = FakeS3()
    assert persist.snapshot(ctx, client=s3, bucket="b") is True
    assert ("b", persist.STATE_KEY) in s3.objects

    # wipe local persona + config, then restore from the snapshot
    (persona.persona_dir(ctx) / "MEMORY.md").unlink()
    os.remove(ctx.config._path) if os.path.exists(ctx.config._path) else None

    assert persist.restore(ctx, client=s3, bucket="b") is True
    assert "ShooterX" in persona.load_memory(ctx)


def test_restore_noop_when_no_snapshot(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    s3 = FakeS3()
    assert persist.restore(ctx, client=s3, bucket="b") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_persist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.persist'`.

- [ ] **Step 3: Implement `persist.py`**

Create `src/gaa/persist.py`:
```python
"""Durable state persistence to VNG vStorage (S3-compatible object storage).

A Custom Agent's filesystem is ephemeral and the runtime can't mount a volume
(verified: agent-runtimes have no volume field; the platform mandates statelessness).
So the durable subset is tarred and PUT to a vStorage bucket on each mutation, and
restored on boot. Runs are NOT persisted (regenerable). If the VSTORAGE_* env vars
are unset, every function is a no-op (local-only) — tests and local dev need no S3.
"""
from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

from gaa.server import persona

STATE_KEY = "gaa-state.tar.gz"


def enabled() -> bool:
    return all(os.environ.get(k) for k in
               ("VSTORAGE_ENDPOINT", "VSTORAGE_BUCKET", "VSTORAGE_ACCESS_KEY", "VSTORAGE_SECRET_KEY"))


def _client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["VSTORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["VSTORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["VSTORAGE_SECRET_KEY"],
    )


def _durable_paths(ctx) -> list[Path]:
    """The files/dirs that must survive a redeploy (absolute paths)."""
    s = ctx.settings
    cache = Path(s.cache_dir)
    candidates = [
        Path(ctx.config._path),          # gaa-config.toml
        Path(s.db_path),                 # gaa.sqlite (profiles)
        cache / "metrics",               # parquet metrics
        Path(os.environ.get("GAA_TOOLS_DIR", str(cache / "tools"))),  # promoted tools
        persona.persona_dir(ctx),        # SOUL.md + MEMORY.md
    ]
    return [p for p in candidates if p.exists()]


def snapshot(ctx, *, client=None, bucket: str | None = None) -> bool:
    """Tar the durable subset and PUT it. Returns False (no-op) if disabled."""
    if client is None:
        if not enabled():
            return False
        client = _client()
    bucket = bucket or os.environ.get("VSTORAGE_BUCKET")
    root = os.path.dirname(os.path.abspath(ctx.settings.cache_dir)) or "/"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in _durable_paths(ctx):
            tar.add(str(p), arcname=os.path.relpath(str(p), root))
    client.put_object(Bucket=bucket, Key=STATE_KEY, Body=buf.getvalue())
    return True


def restore(ctx, *, client=None, bucket: str | None = None) -> bool:
    """Pull the latest snapshot and extract it. Returns False if disabled or none exists."""
    if client is None:
        if not enabled():
            return False
        client = _client()
    bucket = bucket or os.environ.get("VSTORAGE_BUCKET")
    try:
        obj = client.get_object(Bucket=bucket, Key=STATE_KEY)
    except Exception:  # NoSuchKey / first boot
        return False
    data = obj["Body"].read()
    root = os.path.dirname(os.path.abspath(ctx.settings.cache_dir)) or "/"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(root, filter="data")
    return True
```

Note on `root`: durable paths are stored relative to the parent of `cache_dir` so that `data/cache/...`, `gaa.sqlite`, and `gaa-config.toml` (all under the working dir) round-trip to the same layout. The tests set `GAA_CACHE_DIR=<tmp>/cache`, `GAA_DB_PATH=<tmp>/gaa.sqlite`, `GAA_CONFIG_PATH=<tmp>/gaa-config.toml`, so `root = <tmp>` and all arcnames are `cache/...`, `gaa.sqlite`, `gaa-config.toml`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_persist.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/persist.py tests/test_persist.py
git commit -m "feat(server): persist.py — vStorage S3 snapshot/restore of the durable subset"
```

---

## Task 4: `actions.py` — shared action dispatch (CLI handlers via a name map)

**Files:**
- Create: `src/gaa/server/actions.py`
- Test: `tests/server/test_actions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_actions.py`:
```python
import json
import pandas as pd
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import actions

_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {"main_story": "DAU fell.", "rationale": "SEA drop.",
          "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
          "assumptions_and_gaps": []}


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def test_unknown_action(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    r = actions.dispatch(ctx, "nope", {}, is_admin=False)
    assert r["status"] == "error" and "unknown action" in r["error"]


def test_admin_action_refused_without_admin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    r = actions.dispatch(ctx, "config_set", {"key": "benchmark_mode", "value": "crawl"}, is_admin=False)
    assert r["status"] == "error" and "admin" in r["error"].lower()


def test_admin_action_allowed_with_admin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    r = actions.dispatch(ctx, "config_set", {"key": "benchmark_mode", "value": "crawl"}, is_admin=True)
    assert r["status"] == "success"


def test_analyze_dispatch_returns_run_id(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    # onboard a game first (admin)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    actions.dispatch(ctx, "onboard_confirm",
                     {"csv": str(csv), "mapping": json.dumps(_MAPPING), "name": "G",
                      "platform": "roblox", "genre": "survival"}, is_admin=True)
    r = actions.dispatch(ctx, "analyze", {"query": "why did dau drop?", "budget": "0"}, is_admin=False)
    assert "run_id" in r


def test_mutating_set_classification():
    assert "config_set" in actions.MUTATING_ACTIONS
    assert "analyze" not in actions.MUTATING_ACTIONS
    assert "exec" in actions.ADMIN_ACTIONS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_actions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.server.actions'`.

- [ ] **Step 3: Implement `actions.py`**

Create `src/gaa/server/actions.py`:
```python
"""Shared action dispatch: maps an action name + JSON args dict to the existing
CLI handler functions (each `(ctx, args) -> dict`). Both /chat and /invocations
call dispatch(). Capability handlers (exec/browse/self_edit) are registered by
gaa.server.capabilities at import time via register().
"""
from __future__ import annotations

import types

from gaa.cli.main import _cmd_analyze, _cmd_step, _cmd_status, _cmd_jobs
from gaa.cli.commands.primitives import (
    cmd_segments, cmd_detect, cmd_market, cmd_signals, cmd_synth, cmd_report)
from gaa.cli.commands.onboarding import (
    cmd_onboard_propose, cmd_onboard_confirm, cmd_profile_list, cmd_profile_use)
from gaa.cli.commands.config_cmd import cmd_config_get, cmd_config_set
from gaa.cli.commands.doctor import cmd_doctor
from gaa.cli.commands.tools import (
    cmd_tools_list, cmd_tools_show, cmd_tools_promote, cmd_tools_run,
    cmd_tools_remove, cmd_tools_sync_docs, cmd_tools_export, cmd_tools_import)


class _Args(types.SimpleNamespace):
    """Argparse-Namespace stand-in: any attribute a handler reads but we didn't set is None."""
    def __getattr__(self, name):  # only called when normal lookup fails
        return None


# Per-action defaults for attributes the handler will read with a non-None expectation.
_DEFAULTS = {
    "analyze": {"session": "default", "budget": "20", "query": ""},
    "jobs": {"session": None, "prune": None},
    "onboard_propose": {"adapter": "generic"},
    "onboard_confirm": {"adapter": "generic"},
    "tools_sync_docs": {"out": None},
    "tools_export": {"out": None},
}

# Note: handlers reference `args.run` for drilldowns. The model passes "run"; map it.
_HANDLERS = {
    "analyze": _cmd_analyze,
    "step": _cmd_step,
    "status": _cmd_status,
    "jobs": _cmd_jobs,
    "segments": cmd_segments,
    "detect": cmd_detect,
    "market": cmd_market,
    "signals": cmd_signals,
    "synth": cmd_synth,
    "report": cmd_report,
    "onboard_propose": cmd_onboard_propose,
    "onboard_confirm": cmd_onboard_confirm,
    "profile_list": cmd_profile_list,
    "profile_use": cmd_profile_use,
    "config_get": cmd_config_get,
    "config_set": cmd_config_set,
    "doctor": cmd_doctor,
    "tools_list": cmd_tools_list,
    "tools_show": cmd_tools_show,
    "tools_promote": cmd_tools_promote,
    "tools_run": cmd_tools_run,
    "tools_remove": cmd_tools_remove,
    "tools_sync_docs": cmd_tools_sync_docs,
    "tools_export": cmd_tools_export,
    "tools_import": cmd_tools_import,
}

# Actions requiring an admin context (state-changing or dangerous). exec/browse/self_edit
# are added by capabilities.register().
ADMIN_ACTIONS = {
    "config_set", "onboard_confirm", "profile_use", "tools_promote", "tools_run",
    "tools_remove", "tools_import",
}

# Actions whose success should trigger a vStorage snapshot. self_edit is added by register().
MUTATING_ACTIONS = {
    "onboard_confirm", "config_set", "profile_use", "tools_promote", "tools_remove",
    "tools_import",
}


def register(name: str, handler, *, admin: bool = False, mutating: bool = False) -> None:
    """Register a capability handler (called by gaa.server.capabilities)."""
    _HANDLERS[name] = handler
    if admin:
        ADMIN_ACTIONS.add(name)
    if mutating:
        MUTATING_ACTIONS.add(name)


def dispatch(ctx, action: str, args: dict, *, is_admin: bool) -> dict:
    handler = _HANDLERS.get(action)
    if handler is None:
        return {"status": "error", "error": f"unknown action: {action!r}"}
    if action in ADMIN_ACTIONS and not is_admin:
        return {"status": "error", "error": f"action {action!r} requires admin context"}
    merged = dict(_DEFAULTS.get(action, {}))
    merged.update(args or {})
    try:
        return handler(ctx, _Args(**merged))
    except Exception as exc:  # never crash the loop on a bad action
        return {"status": "error", "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_actions.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/actions.py tests/server/test_actions.py
git commit -m "feat(server): actions.py — shared name->handler dispatch with admin/mutating gating"
```

---

## Task 5: `capabilities.py` — exec / browse / self_edit

**Files:**
- Create: `src/gaa/server/capabilities.py`
- Test: `tests/server/test_capabilities.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_capabilities.py`:
```python
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import capabilities, actions, persona


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_exec_runs_command(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    r = capabilities.exec_action(ctx, type("A", (), {"command": "echo hello-gaa"})())
    assert r["status"] == "success"
    assert "hello-gaa" in r["stdout"]


def test_exec_missing_command(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    r = capabilities.exec_action(ctx, type("A", (), {"command": None})())
    assert r["status"] == "error"


def test_browse_extracts_text(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)

    class FakeResp:
        status_code = 200
        text = "<html><head><title>T</title></head><body><p>Hello world</p></body></html>"
        def raise_for_status(self): pass

    monkeypatch.setattr(capabilities.httpx, "get", lambda *a, **k: FakeResp())
    r = capabilities.browse_action(ctx, type("A", (), {"url": "http://x"})())
    assert r["status"] == "success"
    assert "Hello world" in r["text"]
    assert r["title"] == "T"


def test_self_edit_writes_and_is_registered_admin_mutating(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    r = capabilities.self_edit_action(
        ctx, type("A", (), {"target": "MEMORY.md", "content": "Learned: X.", "mode": "append"})())
    assert r["status"] == "success"
    assert "Learned: X." in persona.load_memory(ctx)
    # registered into the shared dispatch as admin + mutating
    assert "exec" in actions.ADMIN_ACTIONS
    assert "self_edit" in actions.MUTATING_ACTIONS


def test_dispatch_routes_exec_when_admin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    r = actions.dispatch(ctx, "exec", {"command": "echo via-dispatch"}, is_admin=True)
    assert r["status"] == "success" and "via-dispatch" in r["stdout"]
    r2 = actions.dispatch(ctx, "exec", {"command": "echo nope"}, is_admin=False)
    assert r2["status"] == "error" and "admin" in r2["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.server.capabilities'`.

- [ ] **Step 3: Implement `capabilities.py`**

Create `src/gaa/server/capabilities.py`:
```python
"""General agent capabilities cloned from OpenClaw: exec (arbitrary shell), browse
(fetch + read a web page), self_edit (rewrite SOUL.md/MEMORY.md). All are admin-gated
(see gaa.server.actions). browse uses httpx + BeautifulSoup (already deps) — no headless
browser, so no JS-rendered pages, but a small image. Each handler is `(ctx, args) -> dict`
to match the CLI handler shape, and is registered into the shared dispatch at import time.
"""
from __future__ import annotations

import subprocess

import httpx
from bs4 import BeautifulSoup

from gaa.server import actions, persona

_EXEC_TIMEOUT_S = 120
_BROWSE_TIMEOUT_S = 30
_BROWSE_MAX_CHARS = 8000


def exec_action(ctx, args) -> dict:
    command = getattr(args, "command", None)
    if not command:
        return {"status": "error", "error": "exec requires a 'command' string"}
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                              timeout=_EXEC_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"command timed out ({_EXEC_TIMEOUT_S}s)"}
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
        **({"error": f"exit {proc.returncode}"} if proc.returncode != 0 else {}),
    }


def browse_action(ctx, args) -> dict:
    url = getattr(args, "url", None)
    if not url:
        return {"status": "error", "error": "browse requires a 'url'"}
    try:
        resp = httpx.get(url, timeout=_BROWSE_TIMEOUT_S, follow_redirects=True,
                         headers={"User-Agent": "gaa-agent/1.0"})
        resp.raise_for_status()
    except Exception as exc:
        return {"status": "error", "error": f"fetch failed: {exc}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = " ".join(soup.get_text(separator=" ").split())
    return {"status": "success", "url": url, "title": title, "text": text[:_BROWSE_MAX_CHARS]}


def self_edit_action(ctx, args) -> dict:
    target = getattr(args, "target", None)
    content = getattr(args, "content", None)
    mode = getattr(args, "mode", None) or "replace"
    if content is None:
        return {"status": "error", "error": "self_edit requires 'content'"}
    try:
        n = persona.write_persona(ctx, target, content, mode=mode)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "target": target, "bytes": n, "mode": mode}


# Register into the shared dispatch (admin-gated; self_edit also triggers a snapshot).
actions.register("exec", exec_action, admin=True)
actions.register("browse", browse_action, admin=True)
actions.register("self_edit", self_edit_action, admin=True, mutating=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_capabilities.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/capabilities.py tests/server/test_capabilities.py
git commit -m "feat(server): capabilities.py — exec/browse/self_edit (admin-gated), registered into dispatch"
```

---

## Task 6: `agent.py` — the manual JSON tool-loop (SSE event generator)

**Files:**
- Create: `src/gaa/server/agent.py`
- Test: `tests/server/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_agent.py`:
```python
import json
import pandas as pd
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import actions, capabilities  # noqa: F401 (capabilities registers exec/etc.)
from gaa.server.agent import ChatAgent


class ScriptedLLM:
    """Returns a queued sequence of decision dicts (one per complete_json call)."""
    def __init__(self, script):
        self._script = list(script)

    def complete_json(self, system, user):
        return self._script.pop(0)


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def _collect(agent, messages, is_admin=False):
    return list(agent.run(messages, is_admin=is_admin))


def test_immediate_final(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    llm = ScriptedLLM([{"final": "Hello, I can analyze your game."}])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "hi"}])
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert "analyze your game" in tokens
    assert events[-1]["type"] == "done"


def test_action_then_final_appends_marker(tmp_path, monkeypatch):
    _SYNTH = {"main_story": "DAU fell.", "rationale": "x",
              "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
              "assumptions_and_gaps": []}
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    actions.dispatch(ctx, "onboard_confirm",
                     {"csv": str(csv), "mapping": json.dumps(
                         {"date_col": "day", "metric_cols": {"dau": "dau"},
                          "dim_cols": {"region": "region"}}),
                      "name": "G", "platform": "roblox", "genre": "survival"}, is_admin=True)
    llm = ScriptedLLM([
        {"action": "analyze", "args": {"query": "why did dau drop?", "budget": "0"}},
        {"final": "Here is what I found."},
    ])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "why did dau drop?"}])
    assert any(e["type"] == "activity" for e in events)
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert "[[gaa:run_id=" in tokens
    assert events[-1]["type"] == "done" and events[-1]["run_id"]


def test_admin_gate_in_loop(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    llm = ScriptedLLM([
        {"action": "exec", "args": {"command": "echo x"}},
        {"final": "done"},
    ])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "run echo"}], is_admin=False)
    # the exec result fed back must be an error; loop still ends with a final
    assert events[-1]["type"] == "done"


def test_max_iterations_terminates(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    # always returns an action, never a final -> must stop at the cap
    llm = ScriptedLLM([{"action": "status", "args": {"run_id": "nope"}}] * 50)
    events = _collect(ChatAgent(ctx, llm, max_iters=5), [{"role": "user", "content": "loop"}])
    assert events[-1]["type"] == "done"
    assert sum(1 for e in events if e["type"] == "activity") <= 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.server.agent'`.

- [ ] **Step 3: Implement `agent.py`**

Create `src/gaa/server/agent.py`:
```python
"""The /chat agent loop — a full clone of the OpenClaw agent, in-process.

Stateless: the caller passes the full messages[]. Each turn we ask the model for ONE
decision JSON ({"action":...}|{"final":...}), dispatch actions in-process (byte-exact
results, no garbling), and stream SSE events. Bounded by max_iters. The most recent
run_id touched is appended to the final answer as a [[gaa:run_id=...]] marker so the
frontend can fetch + render the dossier.
"""
from __future__ import annotations

import json
from typing import Iterator

from gaa.server import actions, persona
from gaa import persist


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "user")
        lines.append(f"{role.upper()}: {m.get('content', '')}")
    return "\n".join(lines)


def _chunk(text: str, size: int = 60) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i:i + size]


class ChatAgent:
    def __init__(self, ctx, llm, *, max_iters: int = 8) -> None:
        self._ctx = ctx
        self._llm = llm
        self._max_iters = max_iters

    def run(self, messages: list[dict], *, is_admin: bool = False) -> Iterator[dict]:
        """Yield SSE event dicts: {"type":"activity"|"token"|"done", ...}."""
        ctx = self._ctx
        system = persona.assemble_system_prompt(ctx, admin=is_admin)
        convo = _format_messages(messages)
        last_run_id = None

        for _ in range(self._max_iters):
            decision = self._llm.complete_json(system, convo)
            if isinstance(decision, dict) and "final" in decision:
                text = str(decision["final"])
                if last_run_id:
                    text += f"\n\n[[gaa:run_id={last_run_id}]]"
                for piece in _chunk(text):
                    yield {"type": "token", "text": piece}
                yield {"type": "done", "run_id": last_run_id}
                return

            action = (decision or {}).get("action")
            a_args = (decision or {}).get("args", {}) or {}
            if not action:
                yield {"type": "token", "text": "(no action or final produced)"}
                yield {"type": "done", "run_id": last_run_id}
                return

            yield {"type": "activity", "text": f"running {action}…"}
            result = actions.dispatch(ctx, action, a_args, is_admin=is_admin)
            if isinstance(result, dict) and result.get("run_id"):
                last_run_id = result["run_id"]
            if (action in actions.MUTATING_ACTIONS
                    and isinstance(result, dict) and result.get("status") == "success"):
                try:
                    persist.snapshot(ctx)
                except Exception:
                    pass  # persistence is best-effort; never break the chat
            convo += f"\nTOOL[{action}] -> {json.dumps(result)[:4000]}"

        # max iterations reached without a final
        yield {"type": "token", "text": "(stopped: reached the tool-iteration limit)"}
        yield {"type": "done", "run_id": last_run_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_agent.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/server/agent.py tests/server/test_agent.py
git commit -m "feat(server): agent.py — manual JSON tool-loop with SSE events + run-id marker"
```

---

## Task 7: `app.py` — FastAPI routes, gating, SSE, artifact serving

**Files:**
- Create: `src/gaa/server/app.py`
- Test: `tests/server/test_app.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_app.py`:
```python
import json
import pandas as pd
from fastapi.testclient import TestClient
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server.app import create_app
from gaa.server import persona

_SYNTH = {"main_story": "DAU fell.", "rationale": "x",
          "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
          "assumptions_and_gaps": []}


class ScriptedLLM:
    def __init__(self, script): self._s = list(script)
    def complete_json(self, system, user): return self._s.pop(0)


def _client(tmp_path, monkeypatch, *, chat_llm=None, preset=_SYNTH, token="t0k", admin="adm"):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    monkeypatch.setenv("GAA_AGENT_TOKEN", token)
    monkeypatch.setenv("GAA_ADMIN_KEY", admin)
    ctx = build_context(llm=FakeLLM(preset), today="2026-06-13")
    persona.ensure_seeded(ctx)
    app = create_app(ctx=ctx, chat_llm=chat_llm)
    return TestClient(app), ctx


def test_health_open(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200


def test_chat_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, chat_llm=ScriptedLLM([{"final": "hi"}]))
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


def test_chat_streams_with_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, chat_llm=ScriptedLLM([{"final": "hello there"}]))
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]},
                    headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 200
    assert "hello there" in r.text  # SSE body contains the streamed tokens


def test_invocations_dispatch(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    r = client.post("/invocations", json={"action": "doctor", "args": {}},
                    headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 200
    assert r.json()["status"] in ("success", "error")  # doctor returns a status


def test_invocations_admin_action_needs_key(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = {"action": "config_set", "args": {"key": "benchmark_mode", "value": "crawl"}}
    r1 = client.post("/invocations", json=body, headers={"Authorization": "Bearer t0k"})
    assert r1.json()["status"] == "error"  # no admin key
    r2 = client.post("/invocations", json={**body, "admin_key": "adm"},
                     headers={"Authorization": "Bearer t0k"})
    assert r2.json()["status"] == "success"


def test_artifact_route_serves_and_blocks_traversal(tmp_path, monkeypatch):
    client, ctx = _client(tmp_path, monkeypatch)
    # create a run dir with a report.html
    run = ctx.runs.create(session="s", query="why", suffix="aaaa")
    (ctx.runs.path_for(run.run_id) / "report.html").write_text("<html>dossier</html>")
    ok = client.get(f"/runs/{run.run_id}/report.html")
    assert ok.status_code == 200 and "dossier" in ok.text
    # traversal / disallowed artifact name
    bad = client.get(f"/runs/{run.run_id}/../../etc/passwd")
    assert bad.status_code in (400, 404)
    bad2 = client.get(f"/runs/{run.run_id}/secret.txt")
    assert bad2.status_code == 404  # not in the artifact allowlist
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_app.py -v`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` for `gaa.server.app`.

- [ ] **Step 3: Implement `app.py`**

Create `src/gaa/server/app.py`:
```python
"""FastAPI app for the GAA Custom Agent (port 8080).

Routes (auth in §7 of the spec):
  POST /chat                  Bearer-gated. SSE stream of the agent loop.
  POST /invocations           Bearer-gated. Structured single-action dispatch.
  GET  /runs/<id>/<artifact>  open, read-only, allowlisted, traversal-safe.
  GET  /health                open.
On startup: persist.restore(ctx) then persona.ensure_seeded(ctx).
"""
from __future__ import annotations

import hmac
import json
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

from gaa.cli.wiring import build_context
from gaa.core.llm.client import LangChainMaaSLLM
from gaa.server import actions, persona
from gaa.server.agent import ChatAgent
from gaa import persist

_ARTIFACTS = {"report.html", "summary.md", "activity.log", "ledger.jsonl", "job.json"}
_CONTENT_TYPES = {
    "report.html": "text/html",
    "summary.md": "text/markdown",
    "activity.log": "text/plain",
    "ledger.jsonl": "application/x-ndjson",
    "job.json": "application/json",
}


def _const_eq(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


def create_app(ctx=None, chat_llm=None) -> FastAPI:
    app = FastAPI(title="GAA Custom Agent")
    state = {"ctx": ctx, "chat_llm": chat_llm}

    def get_ctx():
        if state["ctx"] is None:
            state["ctx"] = build_context()
        return state["ctx"]

    def get_chat_llm():
        if state["chat_llm"] is None:
            state["chat_llm"] = LangChainMaaSLLM(get_ctx().settings)
        return state["chat_llm"]

    def require_token(request: Request):
        if not _const_eq(_bearer(request), os.environ.get("GAA_AGENT_TOKEN")):
            raise HTTPException(status_code=401, detail="missing or invalid agent token")

    @app.on_event("startup")
    def _startup():
        c = get_ctx()
        try:
            persist.restore(c)
        except Exception:
            pass
        persona.ensure_seeded(c)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/chat")
    def chat(request: Request, body: dict):
        require_token(request)
        is_admin = _const_eq(request.headers.get("x-gaa-admin-key"),
                             os.environ.get("GAA_ADMIN_KEY"))
        messages = body.get("messages", [])
        agent = ChatAgent(get_ctx(), get_chat_llm())

        def sse():
            for event in agent.run(messages, is_admin=is_admin):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.post("/invocations")
    def invocations(request: Request, body: dict):
        require_token(request)
        is_admin = _const_eq(body.get("admin_key"), os.environ.get("GAA_ADMIN_KEY"))
        result = actions.dispatch(get_ctx(), body.get("action", ""),
                                  body.get("args", {}) or {}, is_admin=is_admin)
        if (body.get("action") in actions.MUTATING_ACTIONS
                and isinstance(result, dict) and result.get("status") == "success"):
            try:
                persist.snapshot(get_ctx())
            except Exception:
                pass
        return JSONResponse(result)

    @app.get("/runs/{run_id}/{artifact}")
    def artifact(run_id: str, artifact: str):
        if artifact not in _ARTIFACTS:
            raise HTTPException(status_code=404, detail="unknown artifact")
        run_dir = get_ctx().runs.path_for(run_id).resolve()
        path = (run_dir / artifact).resolve()
        if not str(path).startswith(str(run_dir) + os.sep) or not path.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(str(path), media_type=_CONTENT_TYPES[artifact])

    return app


# Production ASGI entrypoint (lazy ctx built on first request / startup).
app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_app.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the whole suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests pass (the prior ~248 plus the new server/persist tests).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/server/app.py tests/server/test_app.py
git commit -m "feat(server): app.py — FastAPI routes, token/admin gating, SSE chat, artifact serving"
```

---

## Task 8: Dockerfile + .dockerignore + local smoke test

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

Create `.dockerignore`:
```
.git
.gitignore
.agentbase
.env
.env.*
**/.env
data/cache
tests
docs
*.md
.venv
__pycache__
**/__pycache__
*.pyc
.pytest_cache
workspace
scripts/openclaw_install.py
```
(Excludes secrets — `.env`, `.agentbase` — and the local run cache; `SOUL.md`/`MEMORY.md` seeds ship as package data under `src/gaa/data/seed/`, NOT the excluded root `*.md`.)

- [ ] **Step 2: Create `Dockerfile`**

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps kept minimal: browse uses httpx + beautifulsoup4 (pure-Python), no chromium.
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[server]"

EXPOSE 8080
CMD ["uvicorn", "gaa.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Build the image (smoke)**

Run: `docker build --platform linux/amd64 -t gaa-custom-agent:smoke .`
Expected: build succeeds.

- [ ] **Step 4: Run the container and hit `/health`**

Run:
```bash
docker run -d --name gaa-smoke -p 8080:8080 \
  -e GAA_AGENT_TOKEN=smoke -e LLM_API_KEY=x -e LLM_MODEL=google/gemma-4-31b-it \
  gaa-custom-agent:smoke
sleep 3
curl -fsS http://localhost:8080/health
docker rm -f gaa-smoke
```
Expected: `{"status":"ok"}`, then container removed.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(server): Dockerfile + .dockerignore — uvicorn :8080, httpx-based browse (no chromium)"
```

---

## Task 9: Plan-doc the deployment + live verification (no new code)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-13-gaa-custom-agent-design.md` (append an "As-built / deploy runbook" appendix only if implementation revealed drift; otherwise skip)

- [ ] **Step 1: Confirm the env contract for deployment**

The runtime env (set via the `agentbase-deploy` skill at deploy time, NOT committed):
- `LLM_BASE_URL` (default MaaS), `LLM_API_KEY`, `LLM_MODEL=google/gemma-4-31b-it` (Gemma 4 for orchestration AND synthesis).
- `PERPLEXITY_API_KEY` (signals), `GAA_BENCHMARK_MODE` (snapshot|crawl).
- `GAA_AGENT_TOKEN` (gates /chat + /invocations), `GAA_ADMIN_KEY` (gates dangerous tools).
- `VSTORAGE_ENDPOINT`, `VSTORAGE_BUCKET`, `VSTORAGE_ACCESS_KEY`, `VSTORAGE_SECRET_KEY` (persistence; unset → local-only no-op).

- [ ] **Step 2: Live verification checklist (run after deploy via the agentbase-deploy skill)**

1. `GET /health` → 200, runtime ACTIVE.
2. `POST /chat` with the agent token + a real "why did <game> drop?" → SSE streams activity + a final ending in `[[gaa:run_id=…]]`.
3. `GET /runs/<id>/report.html` → returns the full self-contained dossier byte-exact.
4. A follow-up drilldown reuses the run_id.
5. `POST /invocations` `config_set` without `admin_key` → error; with the key → success.
6. An `exec`/`browse` round-trip via an admin `/chat` session.
7. **Gemma-4 synthesis re-verification:** run a real analysis end-to-end and confirm the synth stage produces a schema-valid `AttributionHypothesis` (no validation error in the run). If it regresses, set `LLM_MODEL` back to the verified Qwen model for synthesis while keeping Gemma for orchestration (documented fallback in spec §10/§13).
8. `self_edit` MEMORY.md, then redeploy, then confirm the edit survived (vStorage restore on boot).

- [ ] **Step 3: Operational prerequisites (human, one-time)**

- Create a vStorage bucket + S3 access/secret key pair in the VNG Cloud console.
- **Keep** the OpenClaw `gaa` instance for now (live reference for its agent design while building); it is still billed. **Tear it down later** via `/agentbase-teardown` once the Custom Agent is built + verified — do not delete proactively.

- [ ] **Step 4: Commit any as-built notes**

```bash
git add docs/superpowers/specs/2026-06-13-gaa-custom-agent-design.md
git commit -m "docs: as-built deploy runbook for the GAA Custom Agent backend"
```

---

## Self-Review

**Spec coverage check (spec → task):**
- §3 routes (POST /chat SSE, POST /invocations, GET /runs/<id>/<artifact>, GET /health) → Task 7. ✓
- §3 shared GaaContext resolved once at startup → Task 7 (`create_app`/`get_ctx`). ✓
- §4 system prompt = SOUL.md + MEMORY.md + AGENTS red-lines + gaa guide → Task 2 (`assemble_system_prompt`). ✓
- §4 manual JSON tool-loop, bounded iterations, in-process dispatch → Task 6 (`ChatAgent`) + Task 4 (`dispatch`). ✓
- §4 tool set = gaa actions + exec/browse/self_edit → Task 4 + Task 5. ✓
- §4 Gemma 4 for orchestration AND synthesis → Task 7 (`LangChainMaaSLLM`) + Task 9 env (`LLM_MODEL`); synth re-verification → Task 9 step 2.7. ✓
- §4 run_id marker for follow-ups → Task 6 (marker append). ✓
- §4 SSE activity + token events → Task 6 + Task 7. ✓
- §5 artifact serving byte-exact + traversal-safe → Task 7 (`/runs/<id>/<artifact>`). ✓
- §6 vStorage restore-on-boot / snapshot-on-mutation; durable subset incl. SOUL.md/MEMORY.md → Task 3 (`persist.py`) + Task 6/Task 7 (snapshot on mutating success) + Task 7 startup (restore). ✓
- §6 no-op when VSTORAGE_* unset → Task 3 (`enabled()`). ✓
- §7 /chat + /invocations Bearer-gated; artifact/health open → Task 7 (`require_token`). ✓
- §7 two-level: admin key gates exec/browse/self_edit/mutations → Task 4 (`ADMIN_ACTIONS`) + Task 5 (register admin) + Task 7 (admin header/key). ✓
- §8 new files (server/{app,agent,actions,capabilities,persona}.py, persist.py, SOUL.md, MEMORY.md, Dockerfile) → Tasks 1–8. ✓
- §8 new deps fastapi/uvicorn/boto3; browse via existing httpx+bs4 → Task 1 (extras) + Task 5. ✓
- §9 Dockerfile python:3.11-slim, uvicorn :8080; env contract → Task 8 + Task 9. ✓
- §10 offline tests (FakeLLM/ScriptedLLM, auth, self_edit+snapshot, exec, persona, persist round-trip) → Tasks 2–7 tests; live checks → Task 9. ✓
- §13 risk #7 (image weight) resolved: browse uses httpx+bs4, no chromium → Task 5/Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows assertions and the run command + expected result. ✓

**Type/name consistency:** `dispatch(ctx, action, args, *, is_admin)`, `actions.register(name, handler, *, admin, mutating)`, `ADMIN_ACTIONS`/`MUTATING_ACTIONS`, `persona.ensure_seeded/load_soul/load_memory/write_persona/assemble_system_prompt/persona_dir`, `persist.enabled/snapshot/restore/STATE_KEY`, `ChatAgent(ctx, llm, *, max_iters).run(messages, *, is_admin)`, capability handlers `exec_action/browse_action/self_edit_action`, `create_app(ctx=None, chat_llm=None)` — all consistent across tasks. ✓

**Note on streaming fidelity:** Task 6 streams the *completed* final string in 60-char chunks (token-like SSE events), not true LLM token streaming (the `complete_json` client is non-streaming). This is faithful enough for the UI progress experience and fully testable with `ScriptedLLM`; genuine LLM-side token streaming is a later enhancement (would add a `complete_stream` method to the client) and is out of scope for this plan.
