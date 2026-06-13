# GAA Combine — Plan 1: Salvaged Core + CLI + Run Directories

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the deleted HTTP/AgentBase service into a CLI-first tool whose golden path (`gaa analyze` / `step` / `status` / `jobs`) runs the existing 5-stage analysis pipeline against file-based run directories instead of a SQLite job store.

**Architecture:** Keep the proven deterministic analytics untouched but relocate it under `src/gaa/core/` to mark the salvaged/stable boundary. Delete the obsolete orchestration shell (AgentBase app, `GraphAgent`, intent router, `JobStore`, legacy engine). Add three new pieces: `gaa.runs` (a file-backed run-directory model that replaces the job store), `gaa.cli` (the single entry point), and packaging so `pip install -e .` exposes a `gaa` console command. The existing `AnalysisPipeline` is already decoupled from its persistence layer — it only mutates a job-like object — so it is reused almost verbatim, fed a `Run` instead of a `Job`.

**Tech Stack:** Python 3.11, Pydantic v2, pandas/pyarrow, statsmodels, ruptures, argparse, `fcntl.flock` for run locking, pytest.

---

## Scope and relationship to the spec

This is the first of four plans decomposed from `docs/superpowers/specs/2026-06-13-single-agent-combine-design.md`:

1. **Plan 1 (this doc)** — salvaged core + CLI golden path + run directories. Produces a working CLI that onboards data and runs analyses end-to-end.
2. **Plan 2** — TOML runtime config (replaces `ConfigStore`), the six drilldown primitives, `gaa.lab` (Tier 3), tool promotion (Tier 2.5).
3. **Plan 3** — OpenClaw workspace install: `openclaw_install.py`, skill files, `AGENTS.md`, gateway handshake.
4. **Plan 4** — frontend (`vercel/ai-chatbot` clone) + the four-route allowlisted proxy + analysis pane.

Each plan produces independently testable software. Plans 2–4 will be written as their own documents when Plan 1 is complete.

### Decisions made in this plan (divergences from the spec diagram, flagged for review)

- **Physical `core/` directory.** The spec §3 shows `src/gaa/core/`. This plan performs the move (Task 2) as a mechanical, full-test-suite-guarded step. Test *files* keep their current directory layout (`tests/analytics/…`); only their import statements are rewritten — moving test files too would add churn without value, and pytest does not require physical mirroring.
- **`Settings` → `gaa/core/settings.py`.** The old `gaa/config.py` (env/secret settings) moves into core under the name `settings.py`. This frees the top-level `gaa/config.py` name for Plan 2's new TOML runtime-config loader, avoiding two modules both called `config`.
- **`ConfigStore` is kept (under `core/store/`) for Plan 1.** The pipeline's `DynamicRefresher`/`DynamicSignals`/`Synthesizer` wiring still depends on it. Plan 2 migrates it to TOML and deletes it. Keeping it here keeps Plan 1's golden path runnable.
- **Ledger streaming is stage-granular in Plan 1.** `RunStore.save()` rewrites `ledger.jsonl` and `activity.log` as full projections at every stage boundary. True per-entry intra-stage streaming (a ledger file sink) is deferred; stage-granular updates already give the UI live accumulation across the five stages.

If any of these is wrong, say so before execution — they are all reversible but cheaper to change now.

---

## File structure after Plan 1

```
src/gaa/
├── __init__.py
├── core/                       # salvaged, stable (moved in Task 2)
│   ├── __init__.py
│   ├── settings.py             # was gaa/config.py  (Settings: env + secrets + paths)
│   ├── adapters/  analytics/  confidence.py  crawl/  llm/  modules/
│   ├── onboarding/  orchestrator/ (planner.py only)  render/  schema/
│   ├── sources/ (providers/)  store/  synth/
├── runs/                       # NEW — replaces gaa/jobs/
│   ├── __init__.py
│   ├── models.py               # Run (pydantic), duck-types as the old Job
│   ├── slug.py                 # human-readable run-id generation
│   ├── store.py                # RunStore: filesystem persistence + flock + projections
│   └── pipeline.py             # AnalysisPipeline (moved from jobs/, retargeted to Run)
└── cli/                        # NEW — the only entry point
    ├── __init__.py
    ├── wiring.py               # build_pipeline(): composition root (was main.py)
    └── main.py                 # argparse dispatch: analyze / step / status / jobs

tests/
├── core/ … (existing test dirs, imports rewritten — NOT physically moved)
├── runs/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_slug.py
│   ├── test_store.py
│   └── test_pipeline.py        # migrated from tests/jobs/test_pipeline.py
└── cli/
    ├── __init__.py
    └── test_cli.py

DELETED: main.py, src/gaa/graph.py, src/gaa/admin_actions.py, src/gaa/engine.py,
         src/gaa/memory.py, src/gaa/orchestrator/router.py, src/gaa/jobs/,
         Dockerfile (if present), and tests: test_graph*.py, test_admin_actions.py,
         test_engine*.py, test_memory.py, orchestrator/test_router.py, jobs/test_job_store.py
```

**Pre-flight (run once before Task 1):** confirm you are on the empty `main` branch with the salvaged code present in the working tree. The code currently lives on `archive/full-history`; this plan assumes it has been checked out into the working tree on a feature branch off `main`. Run `git status` and `pytest -q` first — record the passing count (expected ~216) so you can attribute later drops to deletions, not breakage.

---

### Task 1: Strip the obsolete HTTP/AgentBase shell

Removes everything that existed only because GAA was a remote service. The deleted code remains recoverable on `archive/full-history`.

**Files:**
- Delete: `main.py`, `src/gaa/graph.py`, `src/gaa/admin_actions.py`, `src/gaa/engine.py`, `src/gaa/memory.py`, `src/gaa/orchestrator/router.py`
- Delete tests: `tests/test_graph.py`, `tests/test_graph_admin.py`, `tests/test_graph_onboarding.py`, `tests/test_admin_actions.py`, `tests/test_engine.py`, `tests/test_engine_full.py`, `tests/test_engine_gate.py`, `tests/test_memory.py`, `tests/orchestrator/test_router.py`
- Modify: `requirements.txt`, `pyproject.toml`, `src/gaa/orchestrator/__init__.py` (if it re-exports `router`)

- [ ] **Step 1: Delete the obsolete source and test files**

```bash
cd ~/Documents/Projects/TestGreenNode
git rm main.py \
       src/gaa/graph.py \
       src/gaa/admin_actions.py \
       src/gaa/engine.py \
       src/gaa/memory.py \
       src/gaa/orchestrator/router.py \
       tests/test_graph.py tests/test_graph_admin.py tests/test_graph_onboarding.py \
       tests/test_admin_actions.py \
       tests/test_engine.py tests/test_engine_full.py tests/test_engine_gate.py \
       tests/test_memory.py \
       tests/orchestrator/test_router.py
# Dockerfile may not exist on the fresh main; remove only if present:
git rm Dockerfile 2>/dev/null || true
```

- [ ] **Step 2: Check for dangling references to deleted modules**

Run: `grep -rn "router\|admin_actions\|gaa.graph\|gaa.engine\|gaa.memory\|GraphAgent\|classify_intent" src/ tests/`
Expected: only matches inside `src/gaa/orchestrator/__init__.py` (if it imports `router`) and possibly `tests/test_config.py`. If `orchestrator/__init__.py` re-exports `classify_intent`/`router`, remove that import line so the package still imports. No other matches should remain.

- [ ] **Step 3: Trim dependencies in `requirements.txt`**

Replace the file contents with (drops `greennode-*` and `langgraph`, which only `main.py`/`memory.py` used):

```
langchain-openai>=1.1.0,<2.0.0
python-dotenv
pandas==2.*
duckdb==1.*
pyarrow==17.*
statsmodels==0.14.*
ruptures==1.1.*
plotly==5.*
jinja2==3.*
httpx>=0.28.1,<1
beautifulsoup4==4.*
pytest==8.*
```

- [ ] **Step 4: Add runtime deps + console entry point to `pyproject.toml`**

Replace the file contents with:

```toml
[project]
name = "gaa"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "langchain-openai>=1.1.0,<2.0.0",
    "python-dotenv",
    "pandas==2.*",
    "duckdb==1.*",
    "pyarrow==17.*",
    "statsmodels==0.14.*",
    "ruptures==1.1.*",
    "plotly==5.*",
    "jinja2==3.*",
    "httpx>=0.28.1,<1",
    "beautifulsoup4==4.*",
]

[project.scripts]
gaa = "gaa.cli.main:cli_entry"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Note: `gaa.cli.main:cli_entry` does not exist yet — it is created in Task 8. That is fine; the entry point is only resolved when `gaa` is invoked, not at install time.

- [ ] **Step 5: Run the remaining suite to confirm only deletions changed the count**

Run: `pytest -q`
Expected: PASS. The total drops by exactly the number of tests in the deleted files. No errors/failures — only a smaller passing count. If anything errors on *collection*, a dangling import survived Step 2; fix it.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: strip obsolete AgentBase/HTTP shell (graph, router, engine, jobs-server, memory)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Relocate the salvaged core under `src/gaa/core/`

A mechanical move guarded entirely by the test suite. No behavior changes.

**Files:**
- Move: every salvaged package/module into `src/gaa/core/`
- Rewrite: all `gaa.<pkg>` imports → `gaa.core.<pkg>` across `src/` and `tests/`; rename `gaa.config` → `gaa.core.settings`

- [ ] **Step 1: Create `core/` and move the salvaged packages**

```bash
cd ~/Documents/Projects/TestGreenNode
mkdir -p src/gaa/core
touch src/gaa/core/__init__.py
git mv src/gaa/adapters src/gaa/analytics src/gaa/crawl src/gaa/llm \
       src/gaa/modules src/gaa/onboarding src/gaa/orchestrator src/gaa/render \
       src/gaa/schema src/gaa/sources src/gaa/store src/gaa/synth \
       src/gaa/confidence.py \
       src/gaa/core/
git mv src/gaa/config.py src/gaa/core/settings.py
```

Note: `src/gaa/jobs/` is intentionally NOT moved — it is dismantled in Task 6. `src/gaa/data/` is also NOT moved — it holds bundled seed/sample assets (not code) and `scripts/build_benchmark_snapshot.py` references it at `src/gaa/data/seed`. `src/gaa/render/templates/` moves *with* `render/` (it is `__file__`-relative, so it self-corrects).

- [ ] **Step 2: Rewrite imports across the codebase**

Run this rewrite (handles both `from gaa.X import` and `import gaa.X`, the `config`→`settings` rename, and protects the already-correct `gaa.core` prefix):

```bash
cd ~/Documents/Projects/TestGreenNode
PKGS="adapters analytics crawl llm modules onboarding orchestrator render schema sources store synth confidence"
FILES=$(grep -rl --include='*.py' 'gaa\.' src tests)
for f in $FILES; do
  # config module rename (must run before the generic prefix pass)
  perl -pi -e 's/\bgaa\.config\b/gaa.core.settings/g' "$f"
  for p in $PKGS; do
    perl -pi -e "s/\\bgaa\\.$p\\b/gaa.core.$p/g unless /gaa\\.core\\.$p/" "$f"
  done
done
```

- [ ] **Step 3: Verify no stale top-level imports remain**

Run: `grep -rnE "gaa\.(adapters|analytics|crawl|llm|modules|onboarding|orchestrator|render|schema|sources|store|synth|confidence|config)\b" src tests | grep -v "gaa\.core\."`
Expected: only matches inside `src/gaa/jobs/` (pipeline/models/job_store still reference `gaa.core.*` correctly after the rewrite — these lines show `gaa.core.` so they are filtered out; if `jobs/` shows any *non*-core `gaa.` import it is a miss). Ideally: **no output**. Any line printed is a missed rewrite — fix it by hand.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS, same count as the end of Task 1. The move is import-only; a green suite proves it.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: relocate salvaged analytics core under src/gaa/core/

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: The `Run` model

A Pydantic model mirroring the old `Job` (so the pipeline accepts it unchanged) plus a `created_at` field. Lives in the new `runs` package.

**Files:**
- Create: `src/gaa/runs/__init__.py` (empty), `src/gaa/runs/models.py`
- Test: `tests/runs/__init__.py` (empty), `tests/runs/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/runs/__init__.py` (empty) and `tests/runs/test_models.py`:

```python
from gaa.runs.models import Run


def test_run_defaults():
    run = Run(run_id="2026-06-13-revenue-drop-k3f9", session="s1", query="why did revenue drop?")
    assert run.stage == "plan"
    assert run.status == "running"
    assert run.state == {}
    assert run.activity == []
    assert run.result is None
    assert run.error is None
    assert run.created_at and run.updated_at


def test_add_activity_appends_entry():
    run = Run(run_id="r1", session="s1", query="q")
    run.add_activity("plan", "scanned metrics")
    assert len(run.activity) == 1
    entry = run.activity[0]
    assert entry["stage"] == "plan"
    assert entry["text"] == "scanned metrics"
    assert "ts" in entry


def test_run_round_trips_through_json():
    run = Run(run_id="r1", session="s1", query="q")
    run.state["metric"] = "revenue"
    run.add_activity("plan", "x")
    restored = Run.model_validate_json(run.model_dump_json())
    assert restored.state["metric"] == "revenue"
    assert restored.activity[0]["text"] == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/runs/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.runs'`.

- [ ] **Step 3: Write the implementation**

Create `src/gaa/runs/__init__.py` (empty) and `src/gaa/runs/models.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Run(BaseModel):
    """A single analysis, persisted as a run directory on disk.

    Field-compatible with the old ``Job`` so ``AnalysisPipeline`` accepts it
    unchanged. ``state`` holds intermediate stage results (including the
    serialized ledger under ``state['ledger']``); ``activity`` is the append-only
    thinking trace; ``result`` is populated at the render stage.
    """

    run_id: str
    session: str
    query: str

    stage: str = "plan"
    status: Literal["running", "done", "error"] = "running"

    state: dict = Field(default_factory=dict)
    activity: list[dict] = Field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    def add_activity(self, stage: str, text: str) -> None:
        """Append an activity entry stamped with the current time."""
        self.activity.append({"ts": _now_iso(), "stage": stage, "text": text})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/runs/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/runs/__init__.py src/gaa/runs/models.py tests/runs/__init__.py tests/runs/test_models.py
git commit -m "feat: Run model for file-backed analysis runs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Human-readable run-id slugs

Run ids are `YYYY-MM-DD-topic-suffix` so the orchestrator can never confuse them with backgrounded-process names, and `gaa jobs` output is self-describing. The date and suffix are injectable for deterministic tests.

**Files:**
- Create: `src/gaa/runs/slug.py`
- Test: `tests/runs/test_slug.py`

- [ ] **Step 1: Write the failing test**

Create `tests/runs/test_slug.py`:

```python
from gaa.runs.slug import slugify_query, make_run_id


def test_slugify_drops_stopwords_and_limits_words():
    assert slugify_query("why did my revenue drop last week?") == "revenue-drop"


def test_slugify_handles_empty_after_stopwords():
    assert slugify_query("why did it?") == "analysis"


def test_make_run_id_is_deterministic_with_explicit_suffix():
    rid = make_run_id("why did revenue drop?", today="2026-06-13", suffix="k3f9")
    assert rid == "2026-06-13-revenue-drop-k3f9"


def test_make_run_id_generates_4char_suffix_when_omitted():
    rid = make_run_id("revenue analysis", today="2026-06-13")
    parts = rid.split("-")
    assert parts[:3] == ["2026", "06", "13"]
    assert len(parts[-1]) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/runs/test_slug.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.runs.slug'`.

- [ ] **Step 3: Write the implementation**

Create `src/gaa/runs/slug.py`:

```python
from __future__ import annotations

import re
import uuid

_STOPWORDS = {
    "the", "a", "an", "why", "did", "do", "does", "my", "is", "are", "was",
    "were", "what", "s", "to", "of", "in", "on", "for", "last", "this", "week",
    "month", "day", "me", "it", "with", "and", "or", "has", "have",
}


def slugify_query(query: str, max_words: int = 4) -> str:
    """Reduce a free-text query to a short hyphenated topic slug."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    kept = [w for w in words if w not in _STOPWORDS][:max_words]
    return "-".join(kept) if kept else "analysis"


def make_run_id(query: str, today: str, suffix: str | None = None) -> str:
    """Build a human-readable run id: ``YYYY-MM-DD-topic-suffix``.

    ``today`` is an ISO date string (caller passes ``date.today().isoformat()``);
    ``suffix`` defaults to a random 4-char hex so concurrent same-topic runs on
    the same day do not collide.
    """
    sfx = suffix or uuid.uuid4().hex[:4]
    return f"{today}-{slugify_query(query)}-{sfx}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/runs/test_slug.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/runs/slug.py tests/runs/test_slug.py
git commit -m "feat: human-readable run-id slug generation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `RunStore` — filesystem persistence with locking and projections

Replaces `JobStore`. Each run is a directory under a root (default `data/runs`). `save()` writes `job.json` and rebuilds the `activity.log` and `ledger.jsonl` projections; on completion it also writes `summary.md` and `report.html`. A `locked()` context manager guards concurrent advances.

**Files:**
- Create: `src/gaa/runs/store.py`
- Test: `tests/runs/test_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/runs/test_store.py`:

```python
import json

import pytest

from gaa.runs.models import Run
from gaa.runs.store import RunStore, RunBusy


def test_create_makes_directory_and_job_json(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="why did revenue drop?", suffix="aaaa")
    assert run.run_id == "2026-06-13-revenue-drop-aaaa"
    assert (tmp_path / run.run_id / "job.json").exists()


def test_get_round_trips(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="bbbb")
    run.state["metric"] = "revenue"
    store.save(run)
    loaded = store.get(run.run_id)
    assert loaded is not None
    assert loaded.state["metric"] == "revenue"


def test_get_unknown_returns_none(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    assert store.get("nope") is None


def test_save_projects_activity_and_ledger(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="cccc")
    run.add_activity("plan", "scanned metrics")
    run.state["ledger"] = [
        {"id": "L1", "module": "anomaly", "claim": "DAU fell", "value": "-30%",
         "source": "internal", "source_type": "internal", "strength": "high"}
    ]
    store.save(run)

    activity = (tmp_path / run.run_id / "activity.log").read_text()
    assert "plan" in activity and "scanned metrics" in activity

    ledger_lines = (tmp_path / run.run_id / "ledger.jsonl").read_text().strip().splitlines()
    assert len(ledger_lines) == 1
    assert json.loads(ledger_lines[0])["id"] == "L1"


def test_save_writes_report_files_when_done(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="dddd")
    run.status = "done"
    run.result = {"markdown_summary": "# Summary", "html": "<html>x</html>"}
    store.save(run)
    assert (tmp_path / run.run_id / "summary.md").read_text() == "# Summary"
    assert (tmp_path / run.run_id / "report.html").read_text() == "<html>x</html>"


def test_list_returns_runs_newest_first(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    a = store.create(session="s1", query="alpha", suffix="0001")
    b = store.create(session="s2", query="beta", suffix="0002")
    b.add_activity("plan", "touch")  # bump updated_at on save
    store.save(b)
    listed = store.list()
    ids = [r["run_id"] for r in listed]
    assert set(ids) == {a.run_id, b.run_id}
    assert ids[0] == b.run_id  # most recently updated first


def test_list_filters_by_session(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    store.create(session="s1", query="alpha", suffix="0001")
    store.create(session="s2", query="beta", suffix="0002")
    s1 = store.list(session="s1")
    assert len(s1) == 1 and s1[0]["session"] == "s1"


def test_locked_raises_runbusy_when_already_held(tmp_path):
    import fcntl
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="eeee")
    lock_path = tmp_path / run.run_id / ".lock"
    held = lock_path.open("w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RunBusy):
            with store.locked(run.run_id):
                pass
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/runs/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.runs.store'`.

- [ ] **Step 3: Write the implementation**

Create `src/gaa/runs/store.py`:

```python
from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

from gaa.runs.models import Run, _now_iso
from gaa.runs.slug import make_run_id


class RunBusy(Exception):
    """Raised when a run directory is locked by another advance in progress."""


class RunStore:
    """Filesystem-backed store of analysis runs.

    Layout: ``<root>/<run_id>/{job.json, activity.log, ledger.jsonl,
    summary.md, report.html, .lock}``.
    """

    def __init__(self, root: str, today: Optional[str] = None) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._today = today or date.today().isoformat()

    # ---- paths ----
    def _dir(self, run_id: str) -> Path:
        return self._root / run_id

    # ---- create / read / write ----
    def create(self, session: str, query: str, suffix: Optional[str] = None) -> Run:
        run_id = make_run_id(query, today=self._today, suffix=suffix)
        run = Run(run_id=run_id, session=session, query=query)
        self._dir(run_id).mkdir(parents=True, exist_ok=True)
        self.save(run)
        return run

    def get(self, run_id: str) -> Optional[Run]:
        path = self._dir(run_id) / "job.json"
        if not path.exists():
            return None
        return Run.model_validate_json(path.read_text())

    def save(self, run: Run) -> None:
        run.updated_at = _now_iso()
        d = self._dir(run.run_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(run.model_dump_json())
        self._write_projections(d, run)

    def _write_projections(self, d: Path, run: Run) -> None:
        lines = [f'{a["ts"]} | {a["stage"]} | {a["text"]}' for a in run.activity]
        (d / "activity.log").write_text("\n".join(lines) + ("\n" if lines else ""))

        ledger = run.state.get("ledger", [])
        with (d / "ledger.jsonl").open("w") as f:
            for entry in ledger:
                f.write(json.dumps(entry) + "\n")

        if run.status == "done" and run.result:
            (d / "summary.md").write_text(run.result.get("markdown_summary", ""))
            (d / "report.html").write_text(run.result.get("html", ""))

    # ---- listing / cleanup ----
    def list(self, session: Optional[str] = None) -> list[dict]:
        out: list[dict] = []
        for child in self._root.iterdir():
            if not child.is_dir():
                continue
            jp = child / "job.json"
            if not jp.exists():
                continue
            run = Run.model_validate_json(jp.read_text())
            if session is not None and run.session != session:
                continue
            out.append({
                "run_id": run.run_id,
                "session": run.session,
                "query": run.query,
                "stage": run.stage,
                "status": run.status,
                "updated_at": run.updated_at,
            })
        out.sort(key=lambda r: r["updated_at"], reverse=True)
        return out

    def prune(self, older_than_iso: str) -> int:
        """Delete runs whose updated_at < older_than_iso; return count removed."""
        import shutil
        removed = 0
        for child in self._root.iterdir():
            jp = child / "job.json"
            if not (child.is_dir() and jp.exists()):
                continue
            run = Run.model_validate_json(jp.read_text())
            if run.updated_at < older_than_iso:
                shutil.rmtree(child)
                removed += 1
        return removed

    # ---- locking ----
    @contextmanager
    def locked(self, run_id: str) -> Iterator[None]:
        """Exclusive non-blocking lock on a run directory.

        Raises :class:`RunBusy` if another process holds the lock, so a
        concurrent caller can fall back to a read-only status instead of
        double-advancing the pipeline.
        """
        d = self._dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        f = (d / ".lock").open("w")
        try:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RunBusy(run_id) from exc
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            finally:
                f.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/runs/test_store.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/runs/store.py tests/runs/test_store.py
git commit -m "feat: RunStore — filesystem runs with flock and file projections

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Move the pipeline into `runs/` and retire `gaa/jobs/`

The pipeline logic is unchanged — it already operates on a duck-typed job object. This task relocates it, retargets the type hint to `Run`, and deletes the now-dead `jobs` package.

**Files:**
- Create: `src/gaa/runs/pipeline.py` (moved from `src/gaa/jobs/pipeline.py`)
- Delete: `src/gaa/jobs/` (entire package: `__init__.py`, `models.py`, `job_store.py`, `pipeline.py`)
- Migrate test: `tests/jobs/test_pipeline.py` → `tests/runs/test_pipeline.py`
- Delete test: `tests/jobs/test_job_store.py` and `tests/jobs/__init__.py`

- [ ] **Step 1: Move the pipeline file**

```bash
cd ~/Documents/Projects/TestGreenNode
git mv src/gaa/jobs/pipeline.py src/gaa/runs/pipeline.py
```

- [ ] **Step 2: Retarget the moved pipeline to `Run`**

In `src/gaa/runs/pipeline.py`, change the job import. Replace this line:

```python
from gaa.jobs.models import Job
```

with:

```python
from gaa.runs.models import Run
```

Then replace the two `Job` type references in the `advance` / `_run_stages` / stage method signatures with `Run`. Specifically change:

```python
    def advance(self, job: Job, deadline: Optional[float] = None) -> Job:
```
to
```python
    def advance(self, job: Run, deadline: Optional[float] = None) -> Run:
```
and
```python
    def _run_stages(self, job: Job, deadline: Optional[float]) -> None:
```
to
```python
    def _run_stages(self, job: Run, deadline: Optional[float]) -> None:
```
and each `def _stage_*(self, job: Job) -> None:` to `def _stage_*(self, job: Run) -> None:` (there are five). The parameter name stays `job` — only the annotation changes — so the body needs no edits. Confirm the `from gaa.core.*` imports at the top are intact from Task 2's rewrite.

- [ ] **Step 3: Delete the dead `jobs` package and its job-store test**

```bash
git rm -r src/gaa/jobs
git rm tests/jobs/test_job_store.py
```

- [ ] **Step 4: Migrate the pipeline test to use `Run` and the new import**

```bash
git mv tests/jobs/test_pipeline.py tests/runs/test_pipeline.py
```

In `tests/runs/test_pipeline.py`, replace the imports:

```python
from gaa.jobs.models import Job
from gaa.jobs.pipeline import AnalysisPipeline
```

with:

```python
from gaa.runs.models import Run
from gaa.runs.pipeline import AnalysisPipeline
```

Then replace every `Job(` constructor call with `Run(` and every `job_id=` keyword with `run_id=`. There are three such constructions:
- in `_Fixtures.make_job`: `return Job(job_id="test-job-001", ...)` → `return Run(run_id="test-job-001", ...)`
- in `test_resume_across_polls_reaches_done`: `Job(job_id="test-job-002", ...)` → `Run(run_id="test-job-002", ...)`
- in `test_no_active_profile_sets_error`: `Job(job_id="err-job", ...)` → `Run(run_id="err-job", ...)`

(The method name `make_job` and local variable names may stay as-is — they are cosmetic.)

- [ ] **Step 5: Remove the empty `tests/jobs` directory**

```bash
rmdir tests/jobs 2>/dev/null || true
```

- [ ] **Step 6: Run the migrated pipeline tests**

Run: `pytest tests/runs/test_pipeline.py -v`
Expected: PASS (5 tests) — full run produces done, activity covers all stages, resume reaches done across polls, no-active-profile errors, stage exception is caught.

- [ ] **Step 7: Confirm no references to `gaa.jobs` survive**

Run: `grep -rn "gaa.jobs" src tests`
Expected: no output.

- [ ] **Step 8: Run the full suite and commit**

Run: `pytest -q`
Expected: PASS.

```bash
git add -A
git commit -m "refactor: move AnalysisPipeline into gaa.runs, retire gaa.jobs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Composition root (`gaa.cli.wiring`)

The single place that constructs stores, sources, the LLM client, and the pipeline — the new equivalent of the old `main.py` wiring. It accepts an optional `llm` so tests can inject `FakeLLM`, and keeps using `ConfigStore` (migrated to TOML in Plan 2).

**Files:**
- Create: `src/gaa/cli/__init__.py` (empty), `src/gaa/cli/wiring.py`
- Test: `tests/cli/__init__.py` (empty), `tests/cli/test_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/cli/__init__.py` (empty) and `tests/cli/test_wiring.py`:

```python
import os

from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM


_PRESET = {
    "main_story": "DAU dropped — internal.",
    "rationale": "SEA drove it.",
    "causes": {"internal": [{"claim": "SEA fell", "evidence_ids": ["L1"], "likelihood": "Likely"}],
               "market": []},
    "scenarios": [], "risks": [], "assumptions_and_gaps": [],
}


def test_build_context_wires_pipeline_and_store(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    ctx = build_context(llm=FakeLLM(_PRESET), today="2026-06-13")
    assert ctx.pipeline is not None
    assert ctx.runs is not None
    assert ctx.profiles is not None
    # run store root lives under the cache dir
    assert "runs" in str(ctx.runs._root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_wiring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.cli.wiring'`.

- [ ] **Step 3: Write the implementation**

Create `src/gaa/cli/__init__.py` (empty) and `src/gaa/cli/wiring.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import gaa as _gaa
from gaa.core.settings import Settings
from gaa.core.llm.client import LangChainMaaSLLM
from gaa.core.onboarding.profiler import Profiler
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.sources.dynamic import DynamicRefresher, DynamicSignals
from gaa.core.store.benchmark_seed import seed_benchmark_store
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.config_store import ConfigStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.profile_store import ProfileStore
from gaa.core.synth.synthesizer import Synthesizer
from gaa.runs.pipeline import AnalysisPipeline
from gaa.runs.store import RunStore


@dataclass
class GaaContext:
    settings: Settings
    profiles: ProfileStore
    metrics: MetricsStore
    config: ConfigStore
    benchmark: CrawlingBenchmarkSource
    profiler: Profiler
    pipeline: AnalysisPipeline
    runs: RunStore
    step_budget_s: float


def build_context(llm: Optional[Any] = None, today: Optional[str] = None) -> GaaContext:
    """Construct every store/source/client once and wire the pipeline.

    ``llm`` defaults to the real MaaS client; tests pass a ``FakeLLM``.
    ``today`` is forwarded to the RunStore for deterministic run ids in tests.
    """
    settings = Settings()

    profiles = ProfileStore(settings.db_path)
    metrics = MetricsStore(settings.cache_dir + "/metrics")

    benchmark_store = BenchmarkStore(settings.cache_dir + "/benchmark.sqlite")
    snapshot_path = os.path.join(
        os.path.dirname(_gaa.__file__), "data", "seed", "benchmark_snapshot.json"
    )
    if os.path.exists(snapshot_path):
        seed_benchmark_store(benchmark_store, snapshot_path)
    benchmark = CrawlingBenchmarkSource(benchmark_store)

    config = ConfigStore(settings.db_path)
    refresher = DynamicRefresher(config=config, settings=settings, store=benchmark_store)
    signals = DynamicSignals(config=config, settings=settings)

    if llm is None:
        llm = LangChainMaaSLLM(settings)
    synth = Synthesizer(llm, instructions_provider=lambda: config.resolve("behavior_instructions")[0])

    pipeline = AnalysisPipeline(
        profiles=profiles,
        metrics_store=metrics,
        benchmark=benchmark,
        refresher=refresher,
        synth=synth,
        signals=signals,
        n_samples=int(os.environ.get("GAA_N_SAMPLES", "3")),
    )
    runs = RunStore(settings.cache_dir + "/runs", today=today)

    return GaaContext(
        settings=settings,
        profiles=profiles,
        metrics=metrics,
        config=config,
        benchmark=benchmark,
        profiler=Profiler(llm),
        pipeline=pipeline,
        runs=runs,
        step_budget_s=float(os.environ.get("GAA_STEP_BUDGET_S", "20")),
    )
```

Note: the seed path is `src/gaa/data/seed/…` — the `data/` directory is intentionally NOT moved into `core/` (Task 2), because it holds bundled assets, not code, and `scripts/build_benchmark_snapshot.py` references `src/gaa/data/seed/benchmark_snapshot.json` by that path. Seeding is guarded by `os.path.exists`, so a wrong path silently yields an empty benchmark rather than crashing — Step 5 verifies the path resolves.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_wiring.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the benchmark seed path resolves**

Run: `python -c "import os, gaa; p=os.path.join(os.path.dirname(gaa.__file__),'data','seed','benchmark_snapshot.json'); print(p, os.path.exists(p))"`
Expected: prints the path and `True`. If `False`, find the seed file (`find src/gaa -name benchmark_snapshot.json`) and correct the path in `wiring.py`.

- [ ] **Step 6: Commit**

```bash
git add src/gaa/cli/__init__.py src/gaa/cli/wiring.py tests/cli/__init__.py tests/cli/test_wiring.py
git commit -m "feat: CLI composition root (build_context) with injectable LLM

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: The CLI — `analyze`, `step`, `status`, `jobs`

The argparse entry point. `analyze` creates a run and advances it within a budget; `step` advances one budget slice under a lock; `status` reads without advancing; `jobs` lists runs. All print compact JSON; heavy artifacts stay in the run directory (only paths are surfaced).

**Files:**
- Create: `src/gaa/cli/main.py`
- Test: `tests/cli/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/cli/test_cli.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.profile_store import ProfileStore


_PRESET = {
    "main_story": "DAU dropped — internal issues.",
    "rationale": "SEA drove most of the decline.",
    "causes": {"internal": [{"claim": "SEA collapsed", "evidence_ids": ["L1"], "likelihood": "Likely"}],
               "market": [{"claim": "Genre flat", "evidence_ids": ["L1"], "likelihood": "Possible"}]},
    "scenarios": [], "risks": [], "assumptions_and_gaps": [],
}


def _seed_workspace(tmp_path):
    """Populate the same paths build_context will read from."""
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")

    profiles = ProfileStore(os.environ["GAA_DB_PATH"])
    profiles.save(GameProfile(
        name="SurvivalGame", platform="roblox", genre="survival",
        mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}),
    ))
    profiles.set_active("SurvivalGame")

    rows = []
    for d, sea, na in [("2026-05-01", 1000.0, 800.0), ("2026-05-03", 400.0, 770.0)]:
        rows.append({"date": d, "metric": "dau", "value": sea, "region": "SEA"})
        rows.append({"date": d, "metric": "dau", "value": na, "region": "NA"})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["platform", "version", "cohort", "device", "source"]:
        df[col] = None
    MetricsStore(os.environ["GAA_CACHE_DIR"] + "/metrics").save("SurvivalGame", df)

    bstore = BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite")
    bstore.put_quant("roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})


def _run(argv, llm):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_analyze_then_status_reaches_done(tmp_path):
    _seed_workspace(tmp_path)
    llm = FakeLLM(_PRESET)

    started = _run(["analyze", "why did dau drop?", "--budget", "0"], llm)
    assert started["run_id"].startswith("2026-06-13-")
    assert started["status"] in ("running", "done")

    run_id = started["run_id"]
    # Drive to completion with repeated steps (budget 0 → one stage per call).
    seen_done = started["done"]
    for _ in range(10):
        if seen_done:
            break
        resp = _run(["step", run_id], llm)
        seen_done = resp["done"]
    assert seen_done, "run did not reach done within 10 steps"

    final = _run(["status", run_id], llm)
    assert final["status"] == "done"
    assert final["report_path"].endswith("report.html")
    assert os.path.exists(final["report_path"])


def test_status_does_not_advance(tmp_path):
    _seed_workspace(tmp_path)
    llm = FakeLLM(_PRESET)
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], llm)
    rid = started["run_id"]
    stage_before = _run(["status", rid], llm)["stage"]
    stage_after = _run(["status", rid], llm)["stage"]
    assert stage_before == stage_after  # pure read never moves the stage


def test_jobs_lists_created_run(tmp_path):
    _seed_workspace(tmp_path)
    llm = FakeLLM(_PRESET)
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], llm)
    listing = _run(["jobs"], llm)
    ids = [r["run_id"] for r in listing["runs"]]
    assert started["run_id"] in ids


def test_status_unknown_run_is_error(tmp_path):
    _seed_workspace(tmp_path)
    resp = _run(["status", "does-not-exist"], FakeLLM(_PRESET))
    assert resp["status"] == "error"
    assert "unknown run" in resp["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.cli.main'`.

- [ ] **Step 3: Write the implementation**

Create `src/gaa/cli/main.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Optional

from gaa.cli.wiring import GaaContext, build_context
from gaa.runs.store import RunBusy


def _run_view(ctx: GaaContext, run) -> dict:
    """Compact status dict. Heavy artifacts stay on disk; only paths surface."""
    d = ctx.runs._dir(run.run_id)
    view = {
        "status": "success",
        "run_id": run.run_id,
        "job_status": run.status,
        "stage": run.stage,
        "done": run.status == "done",
        "activity": run.activity,
        "ledger_count": len(run.state.get("ledger", [])),
    }
    if run.status == "done":
        view["report_path"] = str(d / "report.html")
        view["summary_path"] = str(d / "summary.md")
    if run.status == "error":
        view["error"] = run.error
    return view


def _emit(obj: dict, as_text: bool) -> None:
    if as_text:
        for k, v in obj.items():
            if k == "activity":
                for a in v:
                    print(f'  · [{a["stage"]}] {a["text"]}')
            else:
                print(f"{k}: {v}")
    else:
        print(json.dumps(obj))


def _cmd_analyze(ctx: GaaContext, args) -> dict:
    run = ctx.runs.create(session=args.session, query=args.query)
    budget = max(0.0, min(float(args.budget), ctx.step_budget_s))
    try:
        with ctx.runs.locked(run.run_id):
            ctx.pipeline.advance(run, deadline=time.monotonic() + budget)
            ctx.runs.save(run)
    except RunBusy:
        # Extremely unlikely for a just-created run; report current state.
        run = ctx.runs.get(run.run_id) or run
    return _run_view(ctx, run)


def _cmd_step(ctx: GaaContext, args) -> dict:
    run = ctx.runs.get(args.run_id)
    if run is None:
        return {"status": "error", "error": f"unknown run: {args.run_id!r}"}
    if run.status != "running":
        return _run_view(ctx, run)
    try:
        with ctx.runs.locked(run.run_id):
            # Re-read inside the lock in case another process advanced it.
            run = ctx.runs.get(args.run_id) or run
            if run.status == "running":
                ctx.pipeline.advance(run, deadline=time.monotonic() + ctx.step_budget_s)
                ctx.runs.save(run)
    except RunBusy:
        run = ctx.runs.get(args.run_id) or run
    return _run_view(ctx, run)


def _cmd_status(ctx: GaaContext, args) -> dict:
    run = ctx.runs.get(args.run_id)
    if run is None:
        return {"status": "error", "error": f"unknown run: {args.run_id!r}"}
    return _run_view(ctx, run)


def _cmd_jobs(ctx: GaaContext, args) -> dict:
    if args.prune:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.prune)).isoformat()
        removed = ctx.runs.prune(cutoff)
        return {"status": "success", "pruned": removed}
    return {"status": "success", "runs": ctx.runs.list(session=args.session)}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gaa", description="Game Attribution Agent CLI")
    p.add_argument("--text", action="store_true", help="human-readable output instead of JSON")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="start a new analysis")
    a.add_argument("query")
    a.add_argument("--session", default="default")
    a.add_argument("--budget", default="20", help="seconds of work on this call (clamped to GAA_STEP_BUDGET_S)")

    s = sub.add_parser("step", help="advance a running analysis one budget slice")
    s.add_argument("run_id")

    st = sub.add_parser("status", help="read run status without advancing")
    st.add_argument("run_id")

    j = sub.add_parser("jobs", help="list runs")
    j.add_argument("--session", default=None)
    j.add_argument("--prune", type=int, default=0, metavar="DAYS",
                   help="delete runs older than DAYS instead of listing")
    return p


_DISPATCH = {
    "analyze": _cmd_analyze,
    "step": _cmd_step,
    "status": _cmd_status,
    "jobs": _cmd_jobs,
}


def main(argv: Optional[list] = None, *, llm: Any = None, today: Optional[str] = None) -> dict:
    """Entry point. Returns the response dict (also printed to stdout).

    ``llm`` / ``today`` are injectable for tests; production passes neither.
    """
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        ctx = build_context(llm=llm, today=today)
        result = _DISPATCH[args.command](ctx, args)
    except Exception as exc:  # never raise to the shell with a traceback
        result = {"status": "error", "error": str(exc)}
    _emit(result, as_text=args.text)
    return result


def cli_entry() -> None:
    """console_scripts shim: exit non-zero on error status."""
    result = main()
    raise SystemExit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    cli_entry()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_cli.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS — all salvaged-core tests plus the new `runs/` and `cli/` tests.

- [ ] **Step 6: Commit**

```bash
git add src/gaa/cli/main.py tests/cli/test_cli.py
git commit -m "feat: gaa CLI — analyze/step/status/jobs over run directories

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Install the console entry point and smoke-test it

Confirms `pip install -e .` exposes the `gaa` command and the golden path runs from a real shell against a real (or seeded) workspace.

**Files:**
- No new source. Uses the entry point declared in Task 1 / implemented in Task 8.

- [ ] **Step 1: Editable-install the package**

Run: `pip install -e .`
Expected: succeeds; `gaa` is now on PATH. Verify: `gaa --help` prints the subcommand list (`analyze`, `step`, `status`, `jobs`).

- [ ] **Step 2: Smoke-test against a throwaway workspace**

Without `LLM_API_KEY` set, synthesis will fail at the `synth` stage — that is expected and proves the pipeline reaches synth. Drive the early stages:

```bash
export GAA_CACHE_DIR=/tmp/gaa-smoke/cache
export GAA_DB_PATH=/tmp/gaa-smoke/gaa.sqlite
rm -rf /tmp/gaa-smoke && mkdir -p /tmp/gaa-smoke
# No profile yet → plan stage must report an error cleanly, not crash:
gaa analyze "why did revenue drop?" --budget 0
```
Expected: a JSON line with `"status":"success"`, a dated `run_id`, and (because no profile is active) `"job_status":"error"` with `"error"` mentioning `no active profile`. The command must exit without a Python traceback.

- [ ] **Step 3: Confirm the run directory was written**

Run: `ls /tmp/gaa-smoke/cache/runs/*/`
Expected: a `job.json` and `activity.log` exist for the run created above.

- [ ] **Step 4: Record verification in the commit**

```bash
git commit --allow-empty -m "test: verify gaa console entry point + run-dir smoke (Plan 1 foundation complete)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review (performed against the spec)

- **Golden path (spec §6 Tier 1):** `analyze`/`step`/`status`/`jobs` — Tasks 8. ✓ (`step` mutating vs `status` read-only split — Task 8 `_cmd_step` vs `_cmd_status`.)
- **Run directory model (spec §5):** `job.json`, `activity.log`, `ledger.jsonl`, `summary.md`, `report.html`, human-readable slugs, flock concurrency, stage-granular projections — Tasks 3–6. ✓ (`thinking.md` and `scratch/` are Plan 2 concerns; not created here.)
- **Resumable pipeline preserved (spec §5):** at-least-one-stage guarantee, error marking — reused verbatim, Task 6; covered by migrated `test_pipeline.py`. ✓
- **Fresh shell, salvaged core (spec §3):** strip Task 1, relocate Task 2. ✓
- **`pip install -e .` / console command (spec §12 installer step 3):** Task 1 packaging + Task 9 verify. ✓
- **Type consistency:** `Run` (field `run_id`) is used uniformly across `models.py`, `store.py`, `pipeline.py`, `wiring.py`, `main.py`, and both new test files. `RunStore` method names (`create`/`get`/`save`/`list`/`prune`/`locked`) match every call site. `build_context` returns `GaaContext` whose attributes (`pipeline`, `runs`, `profiles`, `step_budget_s`) match `main.py` usage. ✓
- **Deferred to later plans (intentionally not in Plan 1):** TOML config, primitives, `gaa.lab`, tool promotion (Plan 2); installer + skill files (Plan 3); frontend + proxy (Plan 4). The `ConfigStore` kept here is the explicit bridge.

No placeholders, TODOs, or undefined references remain.

---

## Roadmap: Plans 2–4 (to be written when reached)

**Plan 2 — Config, primitives, lab, tool promotion.**
- Replace `core/store/config_store.py` (SQLite) with `gaa/config.py` (TOML loader + validation); repoint `DynamicRefresher`/`DynamicSignals`/`Synthesizer` and `wiring.build_context` at it; add `gaa config get/set`.
- Add `synthesis.show_thinking` → capture `reasoning_content` into `runs/<id>/thinking.md` (re-enable thinking in `core/llm/client.py` behind the flag).
- Tier 2 primitives: `gaa detect|segments|market|signals|synth|report --run <id>`, each reading the run's plan state and appending provenance-tagged entries to `ledger.jsonl`.
- Tier 3: `gaa/lab.py` (read-only `load_metrics`/`load_benchmark`, `add_evidence` capped at Moderate, `adhoc:` provenance); `runs/<id>/scratch/` convention.
- Tier 2.5: `gaa tools promote|run|list|show|remove|sync-docs|export|import`; `data/tools/` registry with md5 freeze + provenance; `tool:` ledger tags.
- Onboarding CLI: `gaa onboard propose|confirm`, `gaa profile list|use`, `gaa doctor`.

**Plan 3 — OpenClaw workspace install.**
- Rewrite `scripts/openclaw_bootstrap.py` → `openclaw_install.py`: gateway WS handshake, `git clone`/`pull` into workspace, `pip install -e .` (template-image capability gate first), write `.env` + seed `gaa-config.toml`, install `AGENTS.md` + `skills/gaa/` (SKILL.md + references/, md5-verified writes), verify with `gaa doctor` + budgeted smoke `analyze`.

**Plan 4 — Frontend + proxy.**
- Clone `vercel/ai-chatbot`; gut NextAuth/Postgres to single-user; point chat at the `/openclaw/*` SSE passthrough; rebuild the artifacts pane as the analysis pane (poll `/gaa/step`, render `activity.log`/`ledger.jsonl`/`thinking.md`, iframe `report.html`).
- Four allowlisted route handlers: `/openclaw/*`, `POST /gaa/step`, `GET /gaa/run/<id>/<artifact>`, `POST /gaa/onboard`.
