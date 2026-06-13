# GAA Combine — Plan 2c: `gaa.lab` (Tier 3) + Tool Promotion (Tier 2.5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agent (a) write ad-hoc analysis code against a sanctioned, read-only data API that records evidence honestly (Tier 3 — `gaa.lab`), and (b) graduate a proven scratch script into a reusable, md5-frozen tool (Tier 2.5 — `gaa tools`).

**Architecture:** `gaa.lab` is a small module that scratch scripts and promoted tools import: read-only loaders return *copies* of the stores' data, and `add_evidence` appends a ledger entry to a run — capped at Moderate strength and tagged by provenance (`adhoc` for hand-written scratch, `tool:<name>` when run via `gaa tools run`). Tool promotion freezes a copy of a script into a `data/tools/<name>/` registry (`tool.py` + `tool.toml` with an md5 + provenance); `gaa tools run` md5-verifies before executing the frozen copy in a subprocess that injects `GAA_RUN_ID`/`GAA_TOOL_ARGS`/`GAA_TOOL_NAME`. The trust hierarchy is enforced by policy: shipped modules can be Strong; lab/tool evidence is capped at Moderate.

**Tech Stack:** Python 3.11, `hashlib` (md5), `tarfile` (export/import), `tomllib`+`tomli-w` (registry metadata), `subprocess` (tool execution), pytest.

---

## Scope and relationship to the spec

This is **Plan 2c**, the last of the tool-tier plans, covering design spec `2026-06-13-single-agent-combine-design.md` §6 **Tier 3 (`gaa.lab`)** and **Tier 2.5 (tool promotion)**. Builds on Plans 1, 2a, 2b (all merged to `main`): the `gaa` CLI (14 subcommands) with `set_defaults(func=…)` dispatch + command modules, `GaaContext`/`build_context`, the file-backed `RunStore` (`locked`/`path_for`/atomic writes), `GaaConfig`, and `Settings`.

**Deviation from the spec's command names:** the spec wrote `gaa tool run` (singular) alongside `gaa tools promote|list|…` (plural). To avoid two near-identical top-level commands, **everything is consolidated under `gaa tools`**: `promote | run | list | show | remove | sync-docs | export | import`.

**Deferred** (carried over, still out of scope): `synthesis.show_thinking` → `thinking.md` (needs live MaaS `reasoning_content`) and `gaa signals --query`. These belong with Plan 3 (live verification).

**Trust hierarchy (the key policy this plan enforces):** shipped `core/modules` (reviewed, tested) may emit Strong evidence; `gaa.lab.add_evidence` caps strength at **Moderate** (`"med"`) for BOTH ad-hoc scratch and promoted tools. Promotion buys *reuse*, not *trust* — the only path to Strong is a human porting a tool into `core/modules` with tests (a future direction, not built here).

**Execution model (important):** `gaa tools run` does **not** hold the run lock while the subprocess runs — the subprocess's own `lab.add_evidence` acquires the lock (flock is per-process; a parent holding it would deadlock the child into `RunBusy`). The parent only md5-verifies (a read) and spawns.

**Pre-flight:** on `main`, `.venv/bin/python -m pytest -q` shows **225 passed**. Branch: `git switch -c feat/combine-plan-2c`. Tests: `.venv/bin/python -m pytest`. No new dependencies (tomli-w already present from 2a).

---

## File structure after Plan 2c

```
src/gaa/
├── lab.py                      # NEW: Tier-3 read-only data API + evidence sink
├── tools_registry.py           # NEW: ToolRegistry (promote/verify/list/show/remove/sync-docs/export/import)
├── cli/
│   ├── wiring.py               # MODIFIED: expose `tools` (ToolRegistry) on GaaContext
│   ├── main.py                 # MODIFIED: register the nested `tools` command
│   └── commands/
│       └── tools.py            # NEW: thin CLI wrappers + `cmd_tools_run` subprocess exec
tests/
├── test_lab.py                 # NEW: lab read-side + add_evidence
├── test_tools_registry.py      # NEW: ToolRegistry unit tests
└── cli/
    ├── test_tools_cmd.py        # NEW: promote/run/list/show/remove/sync-docs/export/import
    └── test_lab_tool_e2e.py     # NEW: scratch→promote→run→tool-evidence; tamper→refuse
```

---

### Task 1: `gaa.lab` read-side (loaders + execution context)

The read-only data API plus the execution-context helpers a script uses to find its run and args.

**Files:**
- Create: `src/gaa/lab.py`
- Test: `tests/test_lab.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_lab.py`:

```python
import json
import os

import pandas as pd

from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.store.profile_store import ProfileStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.runs.store import RunStore


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    # metrics
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
        "metric": ["dau", "dau"], "value": [1000.0, 400.0], "region": ["SEA", "SEA"],
    })
    for col in ["platform", "version", "cohort", "device", "source"]:
        df[col] = None
    MetricsStore(str(tmp_path / "cache" / "metrics")).save("MyGame", df)
    # benchmark
    BenchmarkStore(str(tmp_path / "cache" / "benchmark.sqlite")).put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 90.0})
    # a run with plan-state
    runs = RunStore(str(tmp_path / "cache" / "runs"), today="2026-06-13")
    run = runs.create(session="s", query="why?", suffix="aaaa")
    run.state.update({"metric": "dau", "start": "2026-05-01", "end": "2026-05-03",
                      "genre": "survival", "platform": "roblox", "profile_name": "MyGame",
                      "ledger": []})
    runs.save(run)
    return run.run_id


def test_run_id_and_args_from_env(tmp_path, monkeypatch):
    import gaa.lab as lab
    monkeypatch.setenv("GAA_RUN_ID", "2026-06-13-x-aaaa")
    monkeypatch.setenv("GAA_TOOL_ARGS", json.dumps({"dim": "region"}))
    assert lab.run_id() == "2026-06-13-x-aaaa"
    assert lab.args() == {"dim": "region"}


def test_args_empty_when_unset(tmp_path, monkeypatch):
    import gaa.lab as lab
    monkeypatch.delenv("GAA_TOOL_ARGS", raising=False)
    assert lab.args() == {}


def test_run_state_and_loaders_return_copies(tmp_path, monkeypatch):
    import gaa.lab as lab
    rid = _workspace(tmp_path, monkeypatch)

    state = lab.run_state(rid)
    assert state["metric"] == "dau" and state["profile_name"] == "MyGame"
    state["metric"] = "MUTATED"  # mutating the copy must not affect the store
    assert lab.run_state(rid)["metric"] == "dau"

    df = lab.load_metrics("MyGame")
    assert len(df) == 2
    df.loc[0, "value"] = -999  # mutating the copy must not affect the store
    assert lab.load_metrics("MyGame")["value"].tolist() == [1000.0, 400.0]

    bench = lab.load_benchmark("survival", "roblox", "2026-05-01", "2026-05-03")
    assert bench  # non-empty indexed series


def test_scratch_dir_created_under_run(tmp_path, monkeypatch):
    import gaa.lab as lab
    rid = _workspace(tmp_path, monkeypatch)
    d = lab.scratch_dir(rid)
    assert d.exists() and d.name == "scratch"
    assert rid in str(d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.lab'`.

- [ ] **Step 3: Write the read-side** — create `src/gaa/lab.py`:

```python
"""Sanctioned read-only data API + evidence sink for ad-hoc analysis (Tier 3).

Scripts — hand-written scratch code, or promoted tools run via `gaa tools run` —
import this to read a run's data and append evidence. All loaders return COPIES,
so a script can never mutate the stores. Evidence added here is capped at Moderate
strength and tagged by provenance: one-shot generated code must not outrank the
reviewed deterministic modules in a cited dossier.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from gaa.core.settings import Settings
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.runs.store import RunStore

_STRENGTH_CAP = {"high": "med", "med": "med", "low": "low"}


def _settings() -> Settings:
    return Settings()


def _runs() -> RunStore:
    return RunStore(_settings().cache_dir + "/runs")


# ---- execution context (set by `gaa tools run`; the agent sets GAA_RUN_ID for scratch) ----
def run_id() -> Optional[str]:
    """The run this script operates on (from GAA_RUN_ID), or None."""
    return os.environ.get("GAA_RUN_ID") or None


def args() -> dict:
    """Parsed GAA_TOOL_ARGS JSON (for promoted tools), or {} if unset/empty."""
    raw = os.environ.get("GAA_TOOL_ARGS", "").strip()
    return json.loads(raw) if raw else {}


# ---- read-only data access (returns copies) ----
def run_state(rid: str) -> dict:
    """A COPY of the run's persisted plan-state (metric/start/end/genre/platform/profile_name/…)."""
    run = _runs().get(rid)
    if run is None:
        raise ValueError(f"unknown run: {rid!r}")
    return dict(run.state)


def load_metrics(game: str):
    """A COPY of the canonical long-format metrics DataFrame for a game."""
    return MetricsStore(_settings().cache_dir + "/metrics").load(game).copy()


def load_benchmark(genre: str, platform: str, start: str, end: str) -> dict:
    """A COPY of the genre benchmark trend (indexed to 100 over the window)."""
    src = CrawlingBenchmarkSource(BenchmarkStore(_settings().cache_dir + "/benchmark.sqlite"))
    src.set_platform(platform)
    return dict(src.genre_trend(genre, start, end))


def scratch_dir(rid: str) -> Path:
    """The sanctioned (created) scratch directory for a run: runs/<id>/scratch/."""
    d = _runs().path_for(rid) / "scratch"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lab.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/lab.py tests/test_lab.py
git commit -m "feat: gaa.lab read-side — read-only loaders + exec-context helpers (Tier 3)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `gaa.lab.add_evidence` (capped, provenance-tagged, run-locked)

**Files:**
- Modify: `src/gaa/lab.py`
- Test: `tests/test_lab.py` (add tests)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_lab.py`:

```python
def test_add_evidence_caps_strength_and_tags_adhoc(tmp_path, monkeypatch):
    import gaa.lab as lab
    from gaa.runs.store import RunStore
    rid = _workspace(tmp_path, monkeypatch)
    monkeypatch.delenv("GAA_TOOL_NAME", raising=False)

    eid = lab.add_evidence(rid, claim="weekend ARPU 2x weekday", value="2.1x",
                           source="scratch/01-arpu.py", strength="high")
    assert eid.startswith("L")
    run = RunStore(os.environ["GAA_CACHE_DIR"] + "/runs").get(rid)
    entry = run.state["ledger"][-1]
    assert entry["strength"] == "med"          # high → capped to Moderate
    assert entry["module"] == "adhoc"          # no GAA_TOOL_NAME → adhoc provenance
    assert entry["claim"] == "weekend ARPU 2x weekday"


def test_add_evidence_tags_tool_when_named(tmp_path, monkeypatch):
    import gaa.lab as lab
    from gaa.runs.store import RunStore
    rid = _workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("GAA_TOOL_NAME", "arpu-split")

    lab.add_evidence(rid, claim="c", value="v", source="tool", strength="low")
    run = RunStore(os.environ["GAA_CACHE_DIR"] + "/runs").get(rid)
    entry = run.state["ledger"][-1]
    assert entry["module"] == "tool:arpu-split"
    assert entry["strength"] == "low"          # low stays low


def test_add_evidence_unknown_run_raises(tmp_path, monkeypatch):
    import gaa.lab as lab
    _workspace(tmp_path, monkeypatch)
    import pytest
    with pytest.raises(ValueError):
        lab.add_evidence("nope", claim="c", value="v", source="s")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_lab.py -k add_evidence -v`
Expected: FAIL — `AttributeError: module 'gaa.lab' has no attribute 'add_evidence'`.

- [ ] **Step 3: Add `add_evidence`** — append to `src/gaa/lab.py`:

```python
def add_evidence(rid: str, *, claim: str, value: str, source: str,
                 strength: str = "med", source_type: str = "derived",
                 timeframe: Optional[str] = None) -> str:
    """Append one ledger entry to a run, under the run's lock.

    Strength is capped at Moderate ("med"). The entry's `module` is tagged
    "tool:<name>" when run via `gaa tools run` (GAA_TOOL_NAME set), else "adhoc".
    Returns the new entry id.
    """
    runs = _runs()
    tool = os.environ.get("GAA_TOOL_NAME", "").strip()
    module = f"tool:{tool}" if tool else "adhoc"
    capped = _STRENGTH_CAP.get(strength, "med")
    with runs.locked(rid):
        run = runs.get(rid)
        if run is None:
            raise ValueError(f"unknown run: {rid!r}")
        ledger = EvidenceLedger()
        ledger.load(run.state.get("ledger", []))
        eid = ledger.add(module=module, claim=claim, value=value, source=source,
                         source_type=source_type, strength=capped, timeframe=timeframe)
        run.state["ledger"] = [e.model_dump() for e in ledger.all()]
        run.add_activity(module, f"ad-hoc evidence: {claim[:60]}")
        runs.save(run)
    return eid
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_lab.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/lab.py tests/test_lab.py
git commit -m "feat: gaa.lab.add_evidence — capped-at-Moderate, provenance-tagged, run-locked

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `ToolRegistry` + `gaa tools promote`

**Files:**
- Create: `src/gaa/tools_registry.py`
- Modify: `src/gaa/cli/wiring.py` (expose `tools`), `src/gaa/cli/main.py` (register `tools promote`)
- Create: `src/gaa/cli/commands/tools.py`
- Test: `tests/test_tools_registry.py`, `tests/cli/test_tools_cmd.py`

- [ ] **Step 1: Write the failing registry test** — create `tests/test_tools_registry.py`:

```python
import pytest

from gaa.tools_registry import ToolRegistry


def _script(tmp_path, body="print('hi')\n"):
    p = tmp_path / "s.py"
    p.write_text(body)
    return str(p)


def test_promote_freezes_copy_with_md5_and_provenance(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    meta = reg.promote("arpu-split", "Split ARPU by weekend/weekday",
                       _script(tmp_path), source_run="run-1", source_script="scratch/01.py")
    assert meta["name"] == "arpu-split"
    assert meta["md5"]
    assert meta["provenance"]["source_run"] == "run-1"
    assert (tmp_path / "tools" / "arpu-split" / "tool.py").exists()
    assert (tmp_path / "tools" / "arpu-split" / "tool.toml").exists()
    assert reg.verify("arpu-split") is True


def test_verify_fails_after_tamper(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    reg.promote("t", "d", _script(tmp_path))
    (tmp_path / "tools" / "t" / "tool.py").write_text("print('tampered')\n")
    assert reg.verify("t") is False


def test_list_show_remove(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    reg.promote("t", "desc", _script(tmp_path))
    listed = reg.list()
    assert listed and listed[0]["name"] == "t" and listed[0]["md5_ok"] is True
    shown = reg.show("t")
    assert shown["description"] == "desc" and "print" in shown["source"]
    reg.remove("t")
    assert reg.list() == []
    with pytest.raises(ValueError):
        reg.show("t")


def test_promote_missing_script_raises(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    with pytest.raises(ValueError):
        reg.promote("t", "d", str(tmp_path / "does-not-exist.py"))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_tools_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.tools_registry'`.

- [ ] **Step 3: Write `ToolRegistry`** — create `src/gaa/tools_registry.py`:

```python
"""Frozen, md5-verified registry of promoted ad-hoc tools (Tier 2.5).

Layout: <root>/<name>/{tool.py (frozen copy), tool.toml (name, description, md5,
provenance)}. Promotion buys reuse, not trust — tool evidence stays Moderate
(enforced in gaa.lab.add_evidence). `verify` gates execution: a drifted/tampered
tool.py refuses to run rather than silently producing different numbers.
"""
from __future__ import annotations

import hashlib
import shutil
import tarfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import tomli_w


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class ToolRegistry:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _dir(self, name: str) -> Path:
        return self._root / name

    def promote(self, name: str, description: str, script_path: str,
                source_run: str = "", source_script: str = "") -> dict:
        src = Path(script_path)
        if not src.exists():
            raise ValueError(f"script not found: {script_path}")
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        tool_py = d / "tool.py"
        shutil.copyfile(src, tool_py)
        meta = {
            "name": name,
            "description": description,
            "md5": _md5(tool_py),
            "provenance": {
                "source_run": source_run,
                "source_script": source_script,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        with (d / "tool.toml").open("wb") as f:
            tomli_w.dump(meta, f)
        return meta

    def meta(self, name: str) -> dict:
        p = self._dir(name) / "tool.toml"
        if not p.exists():
            raise ValueError(f"unknown tool: {name!r}")
        with p.open("rb") as f:
            return tomllib.load(f)

    def path(self, name: str) -> Path:
        return self._dir(name) / "tool.py"

    def verify(self, name: str) -> bool:
        tp = self.path(name)
        return tp.exists() and _md5(tp) == self.meta(name).get("md5")

    def list(self) -> list[dict]:
        out = []
        for child in sorted(self._root.iterdir()):
            if (child / "tool.toml").exists():
                m = self.meta(child.name)
                out.append({
                    "name": m["name"],
                    "description": m.get("description", ""),
                    "promoted_at": m.get("provenance", {}).get("promoted_at", ""),
                    "md5_ok": self.verify(child.name),
                })
        return out

    def show(self, name: str) -> dict:
        m = self.meta(name)
        return {**m, "md5_ok": self.verify(name), "source": self.path(name).read_text()}

    def remove(self, name: str) -> None:
        d = self._dir(name)
        if not d.exists():
            raise ValueError(f"unknown tool: {name!r}")
        shutil.rmtree(d)

    def sync_docs(self, out_path: str) -> str:
        lines = ["# Promoted tools", ""]
        for t in self.list():
            warn = "" if t["md5_ok"] else "  ⚠️ md5 mismatch — re-promote"
            lines.append(f"- **{t['name']}** — {t['description']}{warn}")
        if not self.list():
            lines.append("_(none promoted yet)_")
        text = "\n".join(lines) + "\n"
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        return text

    def export(self, tarball: str) -> None:
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(self._root, arcname=".")

    def import_(self, tarball: str) -> None:
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(self._root, filter="data")
```

- [ ] **Step 4: Run registry tests**

Run: `.venv/bin/python -m pytest tests/test_tools_registry.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Expose `tools` on `GaaContext`** — in `src/gaa/cli/wiring.py`:
- Add import `from gaa.tools_registry import ToolRegistry`.
- Add a `tools: ToolRegistry` field to the `GaaContext` dataclass (after `runs`).
- In `build_context`, construct it and add to the return:
  ```python
  tools = ToolRegistry(os.environ.get("GAA_TOOLS_DIR", settings.cache_dir + "/tools"))
  ```
  and `tools=tools,` in the `return GaaContext(...)`.

- [ ] **Step 6: Write the `tools` command module + `promote`** — create `src/gaa/cli/commands/tools.py`:

```python
from __future__ import annotations

import os


def cmd_tools_promote(ctx, args) -> dict:
    # Resolve the script: relative to the run's scratch dir when --run is given.
    script = args.script
    if args.run and not os.path.isabs(script) and not os.path.exists(script):
        script = str(ctx.runs.path_for(args.run) / "scratch" / args.script)
    try:
        meta = ctx.tools.promote(
            args.name, args.description, script,
            source_run=args.run or "", source_script=args.script)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "tool": meta["name"], "md5": meta["md5"],
            "provenance": meta["provenance"]}
```

- [ ] **Step 7: Write the failing CLI test** — create `tests/cli/test_tools_cmd.py`:

```python
import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    os.environ["GAA_TOOLS_DIR"] = str(tmp_path / "cache" / "tools")


def _run(argv, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def _script(tmp_path, body="print('hi')\n"):
    p = tmp_path / "scratch.py"
    p.write_text(body)
    return str(p)


def test_tools_promote(tmp_path):
    resp = _run(["tools", "promote", "--name", "t", "--description", "d",
                 "--script", _script(tmp_path)], tmp_path)
    assert resp["status"] == "success"
    assert resp["tool"] == "t" and resp["md5"]


def test_tools_promote_missing_script_is_error(tmp_path):
    resp = _run(["tools", "promote", "--name", "t", "--description", "d",
                 "--script", str(tmp_path / "nope.py")], tmp_path)
    assert resp["status"] == "error"
```

- [ ] **Step 8: Register the `tools` command + `promote` in `main.py`**

Add import `from gaa.cli.commands.tools import cmd_tools_promote`. In `_build_parser()`:
```python
    tl = sub.add_parser("tools", help="promote/run/manage ad-hoc tools")
    tl_sub = tl.add_subparsers(dest="tools_command", required=True)
    tlp = tl_sub.add_parser("promote", help="freeze a scratch script into a reusable tool")
    tlp.add_argument("--name", required=True)
    tlp.add_argument("--description", required=True)
    tlp.add_argument("--script", required=True,
                     help="path to the script (relative to the run's scratch/ when --run is given)")
    tlp.add_argument("--run", default=None, help="source run id (for provenance + scratch resolution)")
    tlp.set_defaults(func=cmd_tools_promote)
```

- [ ] **Step 9: Run tests**

Run: `.venv/bin/python -m pytest tests/test_tools_registry.py tests/cli/test_tools_cmd.py -v`
Expected: PASS (6 tests).

- [ ] **Step 10: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/tools_registry.py src/gaa/cli/wiring.py src/gaa/cli/commands/tools.py src/gaa/cli/main.py tests/test_tools_registry.py tests/cli/test_tools_cmd.py
git commit -m "feat: ToolRegistry + gaa tools promote (md5-frozen tool registry)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `gaa tools run` — md5-verify then execute

Executes a frozen tool in a subprocess after md5 verification, injecting `GAA_RUN_ID`/`GAA_TOOL_ARGS`/`GAA_TOOL_NAME`. The parent does NOT hold the run lock (the subprocess's `lab.add_evidence` acquires it).

**Files:**
- Modify: `src/gaa/cli/commands/tools.py` (add `cmd_tools_run`), `src/gaa/cli/main.py`
- Test: `tests/cli/test_tools_cmd.py` (add tests)

- [ ] **Step 1: Write the failing tests** — append to `tests/cli/test_tools_cmd.py`:

```python
import pandas as pd
from gaa.core.llm.client import FakeLLM
from gaa.core.store.benchmark_store import BenchmarkStore

_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {"main_story": "x", "rationale": "y",
          "causes": {"internal": [{"claim": "c", "evidence_ids": ["L1"], "likelihood": "Likely"}], "market": []},
          "scenarios": [], "risks": [], "assumptions_and_gaps": []}


def _run_llm(argv, llm, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def _planned_run(tmp_path):
    """Onboard + plan a run so a tool has a real run to operate on."""
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    _run_llm(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
              "--name", "G", "--platform", "roblox", "--genre", "survival"], FakeLLM(_MAPPING), tmp_path)
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 90.0})
    return _run_llm(["analyze", "why?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)["run_id"]


_TOOL_BODY = (
    "from gaa import lab\n"
    "rid = lab.run_id()\n"
    "st = lab.run_state(rid)\n"
    "df = lab.load_metrics(st['profile_name'])\n"
    "lab.add_evidence(rid, claim='adhoc finding', value=str(len(df)), source='tool')\n"
    "print('ok')\n"
)


def test_tools_run_executes_and_adds_tool_evidence(tmp_path):
    from gaa.runs.store import RunStore
    rid = _planned_run(tmp_path)
    script = tmp_path / "tool_body.py"
    script.write_text(_TOOL_BODY)
    assert _run(["tools", "promote", "--name", "counter", "--description", "row counter",
                 "--script", str(script)], tmp_path)["status"] == "success"

    resp = _run(["tools", "run", "counter", "--run", rid], tmp_path)
    assert resp["status"] == "success", resp
    assert resp["returncode"] == 0

    run = RunStore(os.environ["GAA_CACHE_DIR"] + "/runs").get(rid)
    tool_entries = [e for e in run.state["ledger"] if e["module"] == "tool:counter"]
    assert tool_entries, "expected a tool:counter ledger entry"
    assert tool_entries[-1]["strength"] == "med"  # capped


def test_tools_run_refuses_tampered_tool(tmp_path):
    rid = _planned_run(tmp_path)
    script = tmp_path / "tool_body.py"
    script.write_text(_TOOL_BODY)
    _run(["tools", "promote", "--name", "counter", "--description", "d", "--script", str(script)], tmp_path)
    # tamper with the frozen copy
    (tmp_path / "cache" / "tools" / "counter" / "tool.py").write_text("print('evil')\n")
    resp = _run(["tools", "run", "counter", "--run", rid], tmp_path)
    assert resp["status"] == "error"
    assert "md5" in resp["error"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/cli/test_tools_cmd.py -k "run_executes or tampered" -v`
Expected: FAIL — argparse "invalid choice: 'run'" under `tools` (the `run` subcommand doesn't exist yet).

- [ ] **Step 3: Add `cmd_tools_run`** — append to `src/gaa/cli/commands/tools.py`:

```python
def cmd_tools_run(ctx, args) -> dict:
    import subprocess
    import sys

    try:
        ok = ctx.tools.verify(args.name)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    if not ok:
        return {"status": "error",
                "error": f"tool {args.name!r} failed md5 verification (changed since promotion) — re-promote it"}

    env = {**os.environ, "GAA_TOOL_NAME": args.name}
    if args.run:
        env["GAA_RUN_ID"] = args.run
    if args.args:
        env["GAA_TOOL_ARGS"] = args.args
    try:
        proc = subprocess.run(
            [sys.executable, str(ctx.tools.path(args.name))],
            env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"tool {args.name!r} timed out (120s)"}
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "tool": args.name,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
        **({"error": f"tool exited {proc.returncode}"} if proc.returncode != 0 else {}),
    }
```

- [ ] **Step 4: Register `tools run` in `main.py`**

Extend the import to include `cmd_tools_run`. In `_build_parser()`, add under `tl_sub`:
```python
    tlr = tl_sub.add_parser("run", help="md5-verify and execute a promoted tool")
    tlr.add_argument("name")
    tlr.add_argument("--run", default=None, help="run id the tool operates on")
    tlr.add_argument("--args", default=None, help="JSON args passed to the tool as GAA_TOOL_ARGS")
    tlr.set_defaults(func=cmd_tools_run)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_tools_cmd.py -v`
Expected: PASS. NOTE: these tests spawn a subprocess running `sys.executable` (the venv python, which has `gaa` editable-installed) — confirm the subprocess can `import gaa.lab` (it inherits the env including `GAA_DB_PATH`/`GAA_CACHE_DIR`). If the subprocess can't import `gaa`, investigate PYTHONPATH/install rather than weakening the test.

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/commands/tools.py src/gaa/cli/main.py tests/cli/test_tools_cmd.py
git commit -m "feat: gaa tools run — md5-verified subprocess execution of promoted tools

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `gaa tools list | show | remove`

**Files:**
- Modify: `src/gaa/cli/commands/tools.py`, `src/gaa/cli/main.py`
- Test: `tests/cli/test_tools_cmd.py` (add tests)

- [ ] **Step 1: Write the failing tests** — append to `tests/cli/test_tools_cmd.py`:

```python
def test_tools_list_and_show_and_remove(tmp_path):
    _run(["tools", "promote", "--name", "t", "--description", "desc",
          "--script", _script(tmp_path)], tmp_path)
    listed = _run(["tools", "list"], tmp_path)
    assert listed["status"] == "success"
    assert any(t["name"] == "t" and t["md5_ok"] for t in listed["tools"])

    shown = _run(["tools", "show", "t"], tmp_path)
    assert shown["status"] == "success"
    assert shown["description"] == "desc" and "print" in shown["source"]

    removed = _run(["tools", "remove", "t"], tmp_path)
    assert removed["status"] == "success"
    assert _run(["tools", "list"], tmp_path)["tools"] == []


def test_tools_show_unknown_is_error(tmp_path):
    resp = _run(["tools", "show", "nope"], tmp_path)
    assert resp["status"] == "error"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/cli/test_tools_cmd.py -k "list_and_show or show_unknown" -v`
Expected: FAIL — argparse "invalid choice: 'list'".

- [ ] **Step 3: Add the three commands** — append to `src/gaa/cli/commands/tools.py`:

```python
def cmd_tools_list(ctx, args) -> dict:
    return {"status": "success", "tools": ctx.tools.list()}


def cmd_tools_show(ctx, args) -> dict:
    try:
        return {"status": "success", **ctx.tools.show(args.name)}
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}


def cmd_tools_remove(ctx, args) -> dict:
    try:
        ctx.tools.remove(args.name)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "removed": args.name}
```

- [ ] **Step 4: Register in `main.py`**

Extend the import to include `cmd_tools_list, cmd_tools_show, cmd_tools_remove`. Under `tl_sub`:
```python
    tll = tl_sub.add_parser("list", help="list promoted tools")
    tll.set_defaults(func=cmd_tools_list)
    tls = tl_sub.add_parser("show", help="show a tool's metadata + source")
    tls.add_argument("name")
    tls.set_defaults(func=cmd_tools_show)
    tlrm = tl_sub.add_parser("remove", help="remove a promoted tool")
    tlrm.add_argument("name")
    tlrm.set_defaults(func=cmd_tools_remove)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_tools_cmd.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/commands/tools.py src/gaa/cli/main.py tests/cli/test_tools_cmd.py
git commit -m "feat: gaa tools list/show/remove

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `gaa tools sync-docs | export | import`

**Files:**
- Modify: `src/gaa/cli/commands/tools.py`, `src/gaa/cli/main.py`
- Test: `tests/cli/test_tools_cmd.py` (add tests)

- [ ] **Step 1: Write the failing tests** — append to `tests/cli/test_tools_cmd.py`:

```python
def test_tools_sync_docs_writes_catalog(tmp_path):
    _run(["tools", "promote", "--name", "t", "--description", "the desc",
          "--script", _script(tmp_path)], tmp_path)
    out = tmp_path / "tools.md"
    resp = _run(["tools", "sync-docs", "--out", str(out)], tmp_path)
    assert resp["status"] == "success"
    text = out.read_text()
    assert "the desc" in text and "**t**" in text


def test_tools_export_then_import_roundtrip(tmp_path):
    _run(["tools", "promote", "--name", "t", "--description", "d",
          "--script", _script(tmp_path)], tmp_path)
    tarball = str(tmp_path / "tools.tgz")
    assert _run(["tools", "export", "--out", tarball], tmp_path)["status"] == "success"
    # wipe the registry, then import
    _run(["tools", "remove", "t"], tmp_path)
    assert _run(["tools", "list"], tmp_path)["tools"] == []
    assert _run(["tools", "import", "--tarball", tarball], tmp_path)["status"] == "success"
    assert any(t["name"] == "t" for t in _run(["tools", "list"], tmp_path)["tools"])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/cli/test_tools_cmd.py -k "sync_docs or roundtrip" -v`
Expected: FAIL — argparse "invalid choice: 'sync-docs'".

- [ ] **Step 3: Add the three commands** — append to `src/gaa/cli/commands/tools.py`:

```python
def cmd_tools_sync_docs(ctx, args) -> dict:
    out = args.out or (str(ctx.tools._root / "tools.md"))
    ctx.tools.sync_docs(out)
    return {"status": "success", "doc_path": out}


def cmd_tools_export(ctx, args) -> dict:
    ctx.tools.export(args.out)
    return {"status": "success", "tarball": args.out}


def cmd_tools_import(ctx, args) -> dict:
    try:
        ctx.tools.import_(args.tarball)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "tools": ctx.tools.list()}
```
(`sync-docs` defaults its output to `GAA_TOOLS_DOC_PATH` when set; honor it: replace the `out = args.out or ...` line with `out = args.out or os.environ.get("GAA_TOOLS_DOC_PATH") or str(ctx.tools._root / "tools.md")`. Plan 3 will set `GAA_TOOLS_DOC_PATH` to the skill's `references/tools.md`.)

- [ ] **Step 4: Register in `main.py`**

Extend the import to include `cmd_tools_sync_docs, cmd_tools_export, cmd_tools_import`. Under `tl_sub`:
```python
    tlsd = tl_sub.add_parser("sync-docs", help="regenerate the promoted-tools catalog")
    tlsd.add_argument("--out", default=None, help="output path (default: GAA_TOOLS_DOC_PATH or <tools>/tools.md)")
    tlsd.set_defaults(func=cmd_tools_sync_docs)
    tle = tl_sub.add_parser("export", help="export the tool registry to a tarball")
    tle.add_argument("--out", required=True)
    tle.set_defaults(func=cmd_tools_export)
    tli = tl_sub.add_parser("import", help="import a tool registry tarball")
    tli.add_argument("--tarball", required=True)
    tli.set_defaults(func=cmd_tools_import)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_tools_cmd.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/commands/tools.py src/gaa/cli/main.py tests/cli/test_tools_cmd.py
git commit -m "feat: gaa tools sync-docs/export/import

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Tier-3 → Tier-2.5 end-to-end + console smoke

Proves the full graduation story: write a scratch script that uses `gaa.lab` → run it directly (adds `adhoc` evidence) → promote it → `gaa tools run` it (adds `tool:<name>` evidence) → tamper → run refuses.

**Files:**
- Test: `tests/cli/test_lab_tool_e2e.py`

- [ ] **Step 1: Write the end-to-end test** — create `tests/cli/test_lab_tool_e2e.py`:

```python
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.runs.store import RunStore


_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {"main_story": "x", "rationale": "y",
          "causes": {"internal": [{"claim": "c", "evidence_ids": ["L1"], "likelihood": "Likely"}], "market": []},
          "scenarios": [], "risks": [], "assumptions_and_gaps": []}

_SCRIPT = (
    "from gaa import lab\n"
    "rid = lab.run_id()\n"
    "st = lab.run_state(rid)\n"
    "df = lab.load_metrics(st['profile_name'])\n"
    "lab.add_evidence(rid, claim='rows=' + str(len(df)), value=str(len(df)), source='scratch')\n"
    "print('done', len(df))\n"
)


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    os.environ["GAA_TOOLS_DIR"] = str(tmp_path / "cache" / "tools")


def _run(argv, llm, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_scratch_to_promoted_tool_lifecycle(tmp_path):
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    _run(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
          "--name", "G", "--platform", "roblox", "--genre", "survival"], FakeLLM(_MAPPING), tmp_path)
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 90.0})
    rid = _run(["analyze", "why?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)["run_id"]

    runs = RunStore(os.environ["GAA_CACHE_DIR"] + "/runs")

    # 1. write the scratch script into the run's sanctioned scratch dir, run it directly
    import gaa.lab as lab
    scratch = lab.scratch_dir(rid) / "01-rows.py"
    scratch.write_text(_SCRIPT)
    proc = subprocess.run([sys.executable, str(scratch)],
                          env={**os.environ, "GAA_RUN_ID": rid},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    adhoc = [e for e in runs.get(rid).state["ledger"] if e["module"] == "adhoc"]
    assert adhoc, "scratch run should add an adhoc entry"

    # 2. promote the scratch script
    assert _run(["tools", "promote", "--name", "rows", "--description", "count rows",
                 "--script", "01-rows.py", "--run", rid], FakeLLM(_SYNTH), tmp_path)["status"] == "success"

    # 3. run it as a promoted tool → tool:rows evidence
    resp = _run(["tools", "run", "rows", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success" and resp["returncode"] == 0
    tool_entries = [e for e in runs.get(rid).state["ledger"] if e["module"] == "tool:rows"]
    assert tool_entries

    # 4. tamper with the frozen copy → run refuses
    (tmp_path / "cache" / "tools" / "rows" / "tool.py").write_text("print('evil')\n")
    bad = _run(["tools", "run", "rows", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert bad["status"] == "error" and "md5" in bad["error"].lower()
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/cli/test_lab_tool_e2e.py -v`
Expected: PASS. If a subprocess step fails to import `gaa`, fix the env/install (do not weaken assertions).

- [ ] **Step 3: Real console smoke**

```bash
uv pip install -e . --python .venv/bin/python
.venv/bin/gaa tools --help    # confirm: promote, run, list, show, remove, sync-docs, export, import
.venv/bin/gaa --help          # confirm the top-level surface now includes `tools`
```
Expected: `tools --help` lists all eight subcommands; top-level `--help` includes `tools`. No tracebacks. Paste the `tools` subcommand list.

- [ ] **Step 4: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green; record the count.
```bash
git add tests/cli/test_lab_tool_e2e.py
git commit -m "test: lab→promote→run lifecycle e2e (adhoc + tool evidence, md5 refusal)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review (against the spec)

- **Tier 3 `gaa.lab` (spec §6):** read-only `load_metrics`/`load_benchmark`/`run_state` returning copies (Task 1); `add_evidence` tagged `adhoc`/`tool:<name>` and **capped at Moderate** (Task 2); `scratch_dir` sanctioned location (Task 1). ✓
- **Tier 2.5 tool promotion (spec §6):** `promote` freezes a copy with md5 + provenance (Task 3); `run` md5-verifies before executing and refuses a tampered tool (Task 4); `list`/`show`/`remove` (Task 5); `sync-docs`/`export`/`import` (Task 6). ✓
- **"Promotion buys reuse, not trust" (spec §17):** tool evidence is capped at Moderate in `lab.add_evidence` regardless of provenance — Task 2. ✓
- **md5 refusal:** Task 4 + the e2e (Task 7). ✓
- **Registry survives instance recreate:** `export`/`import` tarball — Task 6. ✓
- **Execution model:** `tools run` doesn't hold the run lock; the subprocess's `add_evidence` locks — documented + exercised by the e2e (a deadlock would manifest as `RunBusy`). ✓
- **Deviation:** consolidated under `gaa tools run` (not `gaa tool run`); noted.
- **Type/interface consistency:** `lab` functions read `GAA_RUN_ID`/`GAA_TOOL_ARGS`/`GAA_TOOL_NAME`; `gaa tools run` sets exactly those; `ToolRegistry` method names match the CLI wrappers; `GaaContext.tools` is a `ToolRegistry`; all command functions take `(ctx, args)` and return `{status, …}`.

No placeholders or undefined references.

## After Plan 2c → Plan 3

The CLI toolbox is complete (analyze/step/status/jobs/doctor/config/onboard/profile + 6 primitives + tools). Next: **Plan 3 — OpenClaw workspace install** (`openclaw_install.py`: gateway handshake, `git clone` + `pip install -e .` capability gate, write `.env` + seed `gaa-config.toml`, install `AGENTS.md` + `skills/gaa/` with `sync-docs` wired to `references/tools.md`, verify via `gaa doctor` + a budgeted smoke `analyze`), then **Plan 4 — frontend + proxy**. The deferred `synthesis.show_thinking`→`thinking.md` pairs with Plan 3's live MaaS verification.

---

## As-built notes (deviations + documented limits)

Plan 2c was executed via subagent-driven development with a final review (APPROVE_WITH_MINORS, all code findings addressed).

1. **Command consolidation:** all tool operations live under `gaa tools …` (promote/run/list/show/remove/sync-docs/export/import) — the spec's `gaa tool run` (singular) became `gaa tools run`.
2. **Review fixes (commit after Task 7):** `sync_docs` collapses whitespace/newlines in tool name+description to prevent markdown injection into the LLM-consumed catalog (load-bearing for Plan 3, which wires `GAA_TOOLS_DOC_PATH` → `references/tools.md`); `gaa tools run <unknown>` now returns a distinct "unknown tool" error (not a misleading md5 failure); a `RunBusy` during a tool's `lab.add_evidence` is re-raised as a clear "run is busy" `RuntimeError` instead of an opaque traceback.

**Documented limits (by design — for Plan 3/4 threat-model docs, NOT bugs):**
- **`gaa.lab` is a *sanctioned API*, not a sandbox.** The Moderate strength cap is enforced for code that goes *through* `lab.add_evidence`; a script could `import EvidenceLedger`/`RunStore` directly and write a `strength="high"` entry. This is acceptable while only the agent's own (trusted) code runs; if untrusted code is ever executed, the cap is not an enforcement boundary.
- **md5 is drift/tamper-*detection*, not tamper-*resistance*.** Anyone who can rewrite `tool.py` can rewrite the recorded md5. It guarantees a *promoted* tool runs the bytes that were promoted (catches accidental edits / partial writes), which is the stated intent — not a security boundary. Don't overstate it in Plan 3/4 docs.
- **Aggregate `evidence_quality` (Strong/Moderate/Weak) is a separate axis** computed by corroboration/volume; tool/adhoc entries still contribute to it, but the per-entry Strong bonus is structurally denied to them — which is exactly what the cap buys.

Final state: **248 tests passing**; `gaa tools` = 8 subcommands; the scratch→promote→run→tamper-refuse lifecycle is verified end-to-end across a real process boundary (the subprocess writes `tool:<name>` evidence the parent reads back). Trust hierarchy enforced: shipped modules can be Strong; lab/tool evidence capped at Moderate.
