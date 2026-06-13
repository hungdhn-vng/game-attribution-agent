# GAA Combine — Plan 2b: Drilldown Primitives (Tier 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six CLI primitives that re-run individual analysis steps against an *existing* run — `gaa detect | segments | market | signals | synth | report --run <id>` — so a follow-up question ("which region drove it?", "re-check vs the market", "answer my new question from the same evidence") is one fast command instead of a whole new analysis.

**Architecture:** Each primitive reconstructs an `AnalysisContext` + `EvidenceLedger` from the target run's persisted plan-state (`run.state`), runs one deterministic module (or the synthesizer / renderer), appends provenance-tagged entries to the run's `ledger.jsonl`, and persists — all under the run's `flock`. A shared helper (`gaa/cli/commands/primitives.py`) owns the lock → load → run → diff-new-entries → save pattern so the four module primitives are ~3 lines each. `synth` re-synthesizes from the (now enriched) ledger; `report` re-renders the dossier. The trust chain is unchanged: modules write the ledger, the citation validator still gates `synth`.

**Tech Stack:** Python 3.11, the salvaged `gaa.core` modules/synth/render, argparse, pytest.

---

## Scope and relationship to the spec

This is **Plan 2b**, covering design spec `2026-06-13-single-agent-combine-design.md` §6 **Tier 2 (primitives)**. It builds on Plans 1 + 2a (both merged to `main`): the `gaa` CLI with `set_defaults(func=…)` dispatch and command modules under `src/gaa/cli/commands/`, `GaaContext` from `gaa.cli.wiring`, the file-backed `RunStore` (with `locked()` / `path_for()` / atomic `job.json`), and `GaaConfig`.

**The next plan, 2c**, covers Tier 3 (`gaa.lab` ad-hoc code) and Tier 2.5 (tool promotion). **Deferred from 2b** (intentional, to avoid touching the signals source / module plumbing for marginal value): `gaa signals --query "..."` (custom search string) — 2b ships `gaa signals --run <id>` running the configured signals source. The `--query` refinement is noted for a later pass.

**Key facts about the analysis modules** (all in `src/gaa/core/modules/`, all `.run(ctx, ledger)`):
- `AnomalyDetection()` — uses `ctx.metric` if set, else picks the most salient metric; sets `ctx.metric/start/end/direction/extras["changepoint"]`; appends one entry.
- `SegmentDecomposition()` — iterates a hardcoded `DIMS` list, runs Adtributor per dimension, appends the most-surprising dimension's elements. **Needs a small `dims` param (Task 1)** so `--dimension` can focus it.
- `MarketBenchmark(source)` — counterfactual vs `source.genre_trend(genre, start, end)`; reads from the benchmark store a prior `analyze` crawl populated.
- `CompetitorSignals(source)` — `source.events(name, genre, start, end)`.

**How `run.state` is shaped** (set by the pipeline's `plan` stage): `{metric, start, end, direction, changepoint, genre, platform, profile_name, ledger}`; after `synth`: also `hypothesis`. Primitives require at least the plan-state (`profile_name`/`metric`/`start`/`end`), so they operate on a run that has completed `plan` (any run created by `analyze` and stepped at least once, or a done run).

**Pre-flight:** on `main`, `.venv/bin/python -m pytest -q` shows **213 passed**. Branch: `git switch -c feat/combine-plan-2b`. Tests: `.venv/bin/python -m pytest`. The package is editable-installed (no new deps in 2b).

---

## File structure after Plan 2b

```
src/gaa/
├── core/modules/segment.py     # MODIFIED: optional `dims` param (backward-compatible)
├── cli/
│   ├── wiring.py               # MODIFIED: expose `synth` + `signals` on GaaContext
│   ├── main.py                 # MODIFIED: register the 6 primitive subcommands
│   └── commands/
│       └── primitives.py       # NEW: shared helper + the 6 primitive functions
tests/
├── modules/test_segment.py     # MODIFIED: add a dims-filter test
└── cli/
    ├── test_primitives.py      # NEW: detect/segments/market/signals/synth/report
    └── test_drilldown_e2e.py   # NEW: analyze→done → drilldown → synth → report
```

---

### Task 1: `SegmentDecomposition` dimension filter

A backward-compatible optional `dims` parameter so the `segments --dimension region` primitive can focus Adtributor on one dimension. Default behavior (all dimensions) is unchanged.

**Files:**
- Modify: `src/gaa/core/modules/segment.py`
- Test: `tests/modules/test_segment.py` (add one test)

- [ ] **Step 1: Write the failing test** — append to `tests/modules/test_segment.py`:

```python
def test_dims_filter_restricts_to_one_dimension():
    import pandas as pd
    from gaa.core.modules.segment import SegmentDecomposition
    from gaa.core.modules.base import AnalysisContext
    from gaa.core.schema.ledger import EvidenceLedger
    from gaa.core.schema.profile import GameProfile, ColumnMapping

    rows = []
    for d, (sea, na, v1, v2) in {
        "2026-05-01": (1000, 800, 900, 900),
        "2026-05-03": (400, 770, 300, 870),
    }.items():
        rows += [
            {"date": d, "metric": "dau", "value": sea, "region": "SEA", "version": "1.0"},
            {"date": d, "metric": "dau", "value": na, "region": "NA", "version": "1.0"},
        ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["platform", "cohort", "device", "source"]:
        df[col] = None
    profile = GameProfile(name="G", platform="roblox", genre="survival",
                          mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}))
    ctx = AnalysisContext(profile=profile, metrics=df, query="q", metric="dau",
                          start="2026-05-01", end="2026-05-03", direction="down")
    ledger = EvidenceLedger()
    SegmentDecomposition(dims=["region"]).run(ctx, ledger)
    # every entry produced must be about the region dimension, never version
    claims = [e.claim for e in ledger.all()]
    assert claims, "expected at least one segment entry"
    assert all("region=" in c or "no segment" in c for c in claims)
    assert not any("version=" in c for c in claims)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/modules/test_segment.py::test_dims_filter_restricts_to_one_dimension -v`
Expected: FAIL — `TypeError: SegmentDecomposition() takes no arguments` (no `dims` param yet).

- [ ] **Step 3: Add the optional `dims` parameter**

In `src/gaa/core/modules/segment.py`, add an `__init__` and iterate the instance's dims. Change the class so it reads:

```python
class SegmentDecomposition:
    name = "segment"

    def __init__(self, dims: list | None = None) -> None:
        self._dims = dims or DIMS

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.metric and ctx.start and ctx.end):
            return
        df = ctx.metrics[ctx.metrics["metric"] == ctx.metric]
        start, end = pd.Timestamp(ctx.start), pd.Timestamp(ctx.end)

        best = None  # (dim, adtributor-result)
        for dim in self._dims:
            if dim not in df.columns or df[dim].isna().all():
                continue
            forecast = df[df["date"] == start].groupby(dim)["value"].sum().to_dict()
            actual = df[df["date"] == end].groupby(dim)["value"].sum().to_dict()
            if not forecast or not actual:
                continue
            res = adtributor_dimension(forecast, actual)
            if best is None or res["surprise"] > best[1]["surprise"]:
                best = (dim, res)

        if best is None:
            ledger.add(module=self.name, claim="no segment dimensions to decompose",
                       value="n/a", source="internal", source_type="derived", strength="low")
            return

        dim, res = best
        for el in res["elements"]:
            ep = el["ep"]
            strength = "high" if abs(ep) >= 0.5 else ("med" if abs(ep) >= 0.2 else "low")
            ledger.add(
                module=self.name,
                claim=f"{dim}={el['key']} explains {ep*100:.0f}% of the {ctx.metric} move",
                value=f"EP {ep*100:.0f}% · surprise {el['surprise']:.3f}",
                source=f"internal:{ctx.metric} by {dim} (Adtributor)",
                source_type="internal",
                strength=strength,
                timeframe=f"{ctx.start}..{ctx.end}",
            )
```

(The only changes from the current file: the new `__init__`, `for dim in self._dims`, and the added `dim not in df.columns` guard so a filtered dim that isn't a column degrades gracefully instead of `KeyError`.)

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/modules/test_segment.py -v`
Expected: PASS — the new test AND all pre-existing segment tests (proving default behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/segment.py tests/modules/test_segment.py
git commit -m "feat: SegmentDecomposition optional dims filter (backward-compatible)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Primitive scaffolding + `gaa segments`

Adds the shared helper and the first primitive. Exposes `synth` + `signals` on `GaaContext` (needed by later primitives).

**Files:**
- Modify: `src/gaa/cli/wiring.py` (expose `synth`, `signals`)
- Create: `src/gaa/cli/commands/primitives.py`
- Modify: `src/gaa/cli/main.py` (register `segments`)
- Test: `tests/cli/test_primitives.py`

- [ ] **Step 1: Expose `synth` and `signals` on `GaaContext`**

In `src/gaa/cli/wiring.py`:
- Add two fields to the `GaaContext` dataclass (after `benchmark`): `synth: Any` and `signals: Any`.
- In `build_context`, the locals `synth` and `signals` already exist; add them to the `return GaaContext(...)` call: `synth=synth,` and `signals=signals,`.

- [ ] **Step 2: Write the failing test** — create `tests/cli/test_primitives.py`:

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


def _onboard_and_plan(tmp_path):
    """Onboard a 2-region game and create a run that has completed its plan stage."""
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)
    _run(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
          "--name", "SurvivalGame", "--platform", "roblox", "--genre", "survival"],
         FakeLLM(_MAPPING), tmp_path)
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})
    # one budget-0 step → plan stage completes, run.state has metric/window/profile
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)
    return started["run_id"]


def test_segments_appends_region_entries(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["segments", "--run", rid, "--dimension", "region"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "segment"
    assert resp["new_entries"], "expected new ledger entries"
    assert all("region=" in e["claim"] or "no segment" in e["claim"] for e in resp["new_entries"])
    assert resp["ledger_count"] >= len(resp["new_entries"])


def test_segments_unknown_run_is_error(tmp_path):
    _env(tmp_path)
    resp = _run(["segments", "--run", "nope"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "error"
    assert "unknown run" in resp["error"].lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -v`
Expected: FAIL — argparse "invalid choice: 'segments'".

- [ ] **Step 4: Write the shared helper + segments** — create `src/gaa/cli/commands/primitives.py`:

```python
from __future__ import annotations

from typing import Callable

from gaa.core.modules.anomaly import AnomalyDetection
from gaa.core.modules.competitor_signals import CompetitorSignals
from gaa.core.modules.market_benchmark import MarketBenchmark
from gaa.core.modules.segment import SegmentDecomposition
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.runs.store import RunBusy


def load_run_context(ctx, run):
    """Reconstruct (AnalysisContext, EvidenceLedger) from a run's persisted plan-state.

    Raises ValueError if the run has not completed its plan stage (no profile_name).
    """
    state = run.state
    name = state.get("profile_name")
    if not name:
        raise ValueError("run has no plan-state yet — start it with `gaa analyze` first")
    profile = ctx.profiles.get(name)
    if profile is None:
        raise ValueError(f"profile {name!r} no longer exists")
    df = ctx.metrics.load(name)
    actx = AnalysisContext(
        profile=profile, metrics=df, query=run.query,
        metric=state.get("metric"), start=state.get("start"), end=state.get("end"),
        direction=state.get("direction"), extras={"changepoint": state.get("changepoint")},
    )
    ledger = EvidenceLedger()
    ledger.load(state.get("ledger", []))
    return actx, ledger


def run_module_primitive(ctx, run_id: str, module_label: str,
                         body: Callable[[AnalysisContext, EvidenceLedger], None]) -> dict:
    """Lock the run, reconstruct context+ledger, invoke body (which appends to the
    ledger), persist the enriched ledger, and report only the newly-added entries."""
    run = ctx.runs.get(run_id)
    if run is None:
        return {"status": "error", "error": f"unknown run: {run_id!r}"}
    try:
        with ctx.runs.locked(run_id):
            run = ctx.runs.get(run_id) or run
            actx, ledger = load_run_context(ctx, run)
            before = len(ledger.all())
            body(actx, ledger)
            new_entries = [e.model_dump() for e in ledger.all()[before:]]
            run.state["ledger"] = [e.model_dump() for e in ledger.all()]
            run.add_activity(module_label, f"drilldown added {len(new_entries)} ledger entr"
                             f"{'y' if len(new_entries) == 1 else 'ies'}")
            ctx.runs.save(run)
    except RunBusy:
        return {"status": "error", "error": f"run {run_id!r} is busy (another step in progress)"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "run_id": run_id, "module": module_label,
            "new_entries": new_entries, "ledger_count": before + len(new_entries)}


def cmd_segments(ctx, args) -> dict:
    dims = [args.dimension] if args.dimension else None
    return run_module_primitive(
        ctx, args.run, "segment",
        lambda actx, ledger: SegmentDecomposition(dims=dims).run(actx, ledger))


def cmd_detect(ctx, args) -> dict:
    def body(actx, ledger):
        if args.metric:
            actx.metric = args.metric
        AnomalyDetection().run(actx, ledger)
    return run_module_primitive(ctx, args.run, "anomaly", body)


def cmd_market(ctx, args) -> dict:
    return run_module_primitive(
        ctx, args.run, "market",
        lambda actx, ledger: MarketBenchmark(ctx.benchmark).run(actx, ledger))


def cmd_signals(ctx, args) -> dict:
    return run_module_primitive(
        ctx, args.run, "competitor",
        lambda actx, ledger: CompetitorSignals(ctx.signals).run(actx, ledger))
```

(Note: `cmd_detect`/`cmd_market`/`cmd_signals` are included here now but only wired in Task 3 — defining them together keeps the helper file cohesive.)

- [ ] **Step 5: Register `segments` in `main.py`**

Add import `from gaa.cli.commands.primitives import cmd_segments`. In `_build_parser()`:
```python
    seg = sub.add_parser("segments", help="decompose a run's movement by segment (Adtributor)")
    seg.add_argument("--run", required=True)
    seg.add_argument("--dimension", default=None,
                     help="focus one dimension (region/version/cohort/device/source/platform)")
    seg.set_defaults(func=cmd_segments)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/wiring.py src/gaa/cli/commands/primitives.py src/gaa/cli/main.py tests/cli/test_primitives.py
git commit -m "feat: gaa segments primitive + shared drilldown scaffolding

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `gaa detect`, `gaa market`, `gaa signals`

Wire the three remaining module primitives (functions already written in Task 2's `primitives.py`).

**Files:**
- Modify: `src/gaa/cli/main.py`
- Test: `tests/cli/test_primitives.py` (add tests)

- [ ] **Step 1: Write the failing tests** — append to `tests/cli/test_primitives.py`:

```python
def test_detect_appends_anomaly_entry(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["detect", "--run", rid, "--metric", "dau"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "anomaly"
    assert any("dau" in e["claim"] for e in resp["new_entries"])


def test_market_appends_entry(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["market", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "market"
    assert resp["new_entries"]  # either a counterfactual verdict or a graceful "no benchmark" gap


def test_signals_appends_entry(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["signals", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "competitor"
    # with no configured signals source, the module records a "no signals" gap entry
    assert resp["new_entries"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -k "detect or market or signals" -v`
Expected: FAIL — argparse "invalid choice: 'detect'" (etc.).

- [ ] **Step 3: Register the three commands in `main.py`**

Extend the primitives import: `from gaa.cli.commands.primitives import cmd_segments, cmd_detect, cmd_market, cmd_signals`. In `_build_parser()`:
```python
    det = sub.add_parser("detect", help="re-run change-point / anomaly detection")
    det.add_argument("--run", required=True)
    det.add_argument("--metric", default=None, help="target a specific metric")
    det.set_defaults(func=cmd_detect)

    mkt = sub.add_parser("market", help="re-run the market counterfactual")
    mkt.add_argument("--run", required=True)
    mkt.set_defaults(func=cmd_market)

    sig = sub.add_parser("signals", help="re-fetch competitor/event signals")
    sig.add_argument("--run", required=True)
    sig.set_defaults(func=cmd_signals)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -v`
Expected: PASS (5 tests now).

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/main.py tests/cli/test_primitives.py
git commit -m "feat: gaa detect/market/signals drilldown primitives

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `gaa synth` — re-synthesize from the current ledger

Produces a fresh `AttributionHypothesis` from the run's (possibly enriched) ledger, optionally answering a new question, and stores it back into `run.state["hypothesis"]`. Mirrors the pipeline's `synth` stage (concurrent samples → gate → citation validator).

**Files:**
- Modify: `src/gaa/cli/commands/primitives.py` (add `cmd_synth`), `src/gaa/cli/main.py`
- Test: `tests/cli/test_primitives.py` (add tests)

- [ ] **Step 1: Write the failing test** — append to `tests/cli/test_primitives.py`:

```python
def test_synth_produces_hypothesis_from_ledger(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    # enrich the ledger first so synth has something beyond the plan entry
    _run(["segments", "--run", rid, "--dimension", "region"], FakeLLM(_SYNTH), tmp_path)
    resp = _run(["synth", "--run", rid, "is it the SEA region?"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["main_story"] == "DAU dropped — internal."
    assert resp["confidence"]["likelihood"] in ("Very likely", "Likely", "Possible", "Unlikely")


def test_synth_unknown_run_is_error(tmp_path):
    _env(tmp_path)
    resp = _run(["synth", "--run", "nope", "q"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "error"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -k synth -v`
Expected: FAIL — argparse "invalid choice: 'synth'".

- [ ] **Step 3: Add `cmd_synth`** — append to `src/gaa/cli/commands/primitives.py`:

```python
def cmd_synth(ctx, args) -> dict:
    from gaa.core.synth.concurrent import sample_concurrently
    from gaa.core.synth.gate import apply_gate
    from gaa.core.synth.validator import validate_citations

    run = ctx.runs.get(args.run)
    if run is None:
        return {"status": "error", "error": f"unknown run: {args.run!r}"}
    try:
        with ctx.runs.locked(args.run):
            run = ctx.runs.get(args.run) or run
            ledger = EvidenceLedger()
            ledger.load(run.state.get("ledger", []))
            if not ledger.all():
                return {"status": "error", "error": "run has no evidence yet — run `gaa analyze`/drilldowns first"}
            query = args.question or run.query
            samples = sample_concurrently(ctx.synth, ledger, query, ctx.pipeline.n_samples)
            if not samples:
                samples = [ctx.synth.synthesize(ledger, query)]
            hyp = apply_gate(samples[0], samples)
            hyp = validate_citations(hyp, ledger)
            run.state["hypothesis"] = hyp.model_dump()
            run.add_activity("synth", f"re-synthesized for: {query}")
            ctx.runs.save(run)
    except RunBusy:
        return {"status": "error", "error": f"run {args.run!r} is busy (another step in progress)"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {
        "status": "success",
        "run_id": args.run,
        "main_story": hyp.main_story,
        "confidence": {"likelihood": hyp.confidence.likelihood,
                       "evidence_quality": hyp.confidence.evidence_quality},
    }
```

- [ ] **Step 4: Register `synth` in `main.py`**

Extend the import to include `cmd_synth`. In `_build_parser()`:
```python
    syn = sub.add_parser("synth", help="re-synthesize a hypothesis from the run's current ledger")
    syn.add_argument("--run", required=True)
    syn.add_argument("question", nargs="?", default=None,
                     help="optional follow-up question (defaults to the run's original query)")
    syn.set_defaults(func=cmd_synth)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -k synth -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/commands/primitives.py src/gaa/cli/main.py tests/cli/test_primitives.py
git commit -m "feat: gaa synth — re-synthesize hypothesis from current ledger

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `gaa report` — re-render the dossier

Re-renders the HTML + markdown from the run's current `hypothesis` and writes them into the run directory. Mirrors the pipeline's `render` stage.

**Files:**
- Modify: `src/gaa/cli/commands/primitives.py` (add `cmd_report`), `src/gaa/cli/main.py`
- Test: `tests/cli/test_primitives.py` (add tests)

- [ ] **Step 1: Write the failing test** — append to `tests/cli/test_primitives.py`:

```python
def test_report_writes_dossier_files(tmp_path):
    import os as _os
    rid = _onboard_and_plan(tmp_path)
    _run(["segments", "--run", rid, "--dimension", "region"], FakeLLM(_SYNTH), tmp_path)
    _run(["synth", "--run", rid, "why?"], FakeLLM(_SYNTH), tmp_path)
    resp = _run(["report", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["report_path"].endswith("report.html")
    assert _os.path.exists(resp["report_path"])
    assert _os.path.exists(resp["summary_path"])
    html = open(resp["report_path"]).read().lower()
    assert "<html" in html


def test_report_without_hypothesis_is_error(tmp_path):
    rid = _onboard_and_plan(tmp_path)  # plan only, no synth
    resp = _run(["report", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "error"
    assert "synth" in resp["error"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -k report -v`
Expected: FAIL — argparse "invalid choice: 'report'".

- [ ] **Step 3: Add `cmd_report`** — append to `src/gaa/cli/commands/primitives.py`:

```python
def cmd_report(ctx, args) -> dict:
    from gaa.core.render.report import render_report
    from gaa.core.render.markdown import to_markdown
    from gaa.core.schema.hypothesis import AttributionHypothesis

    run = ctx.runs.get(args.run)
    if run is None:
        return {"status": "error", "error": f"unknown run: {args.run!r}"}
    try:
        with ctx.runs.locked(args.run):
            run = ctx.runs.get(args.run) or run
            hyp_raw = run.state.get("hypothesis")
            if not hyp_raw:
                return {"status": "error", "error": "no hypothesis yet — run `gaa synth` first"}
            hyp = AttributionHypothesis.model_validate(hyp_raw)
            df = ctx.metrics.load(run.state["profile_name"])
            metric = run.state.get("metric")
            if metric:
                series = df[df["metric"] == metric].groupby("date")["value"].sum().sort_index()
            else:
                series = df.groupby("date")["value"].sum().sort_index()
            start = run.state.get("start") or ""
            end = run.state.get("end") or ""
            genre_trend: dict = {}
            if run.state.get("start"):
                genre_trend = ctx.benchmark.genre_trend(
                    run.state["genre"], run.state["start"], run.state["end"])
            html = render_report(hyp, metric=metric or "metric", start=start, end=end,
                                 series=series, genre_trend=genre_trend)
            md = to_markdown(hyp)
            run.result = {"hypothesis": hyp.model_dump(), "markdown_summary": md, "html": html}
            run.status = "done"  # a complete dossier now exists; save() writes the files
            run.add_activity("render", "Report re-rendered.")
            ctx.runs.save(run)
    except RunBusy:
        return {"status": "error", "error": f"run {args.run!r} is busy (another step in progress)"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    d = ctx.runs.path_for(args.run)
    return {"status": "success", "run_id": args.run,
            "report_path": str(d / "report.html"), "summary_path": str(d / "summary.md")}
```

- [ ] **Step 4: Register `report` in `main.py`**

Extend the import to include `cmd_report`. In `_build_parser()`:
```python
    rep = sub.add_parser("report", help="re-render the dossier from the run's current hypothesis")
    rep.add_argument("--run", required=True)
    rep.set_defaults(func=cmd_report)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/cli/test_primitives.py -k report -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green.
```bash
git add src/gaa/cli/commands/primitives.py src/gaa/cli/main.py tests/cli/test_primitives.py
git commit -m "feat: gaa report — re-render dossier from current hypothesis

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Drilldown end-to-end test + console smoke

Proves the follow-up workflow: full analysis → drill into a dimension → re-synthesize on the enriched ledger → re-render.

**Files:**
- Test: `tests/cli/test_drilldown_e2e.py`

- [ ] **Step 1: Write the end-to-end test** — create `tests/cli/test_drilldown_e2e.py`:

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


def _run(argv, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=FakeLLM(_SYNTH), today="2026-06-13")
    return json.loads(buf.getvalue())


def test_drilldown_then_resynth_then_report(tmp_path):
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)

    # onboard (uses a mapping-shaped FakeLLM)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
              "--name", "SurvivalGame", "--platform", "roblox", "--genre", "survival"],
             llm=FakeLLM(_MAPPING), today="2026-06-13")
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})

    # full analysis to done
    started = _run(["analyze", "why did dau drop?"], tmp_path)
    rid = started["run_id"]
    done = started["done"]
    for _ in range(10):
        if done:
            break
        done = _run(["step", rid], tmp_path)["done"]
    assert done

    count_before = _run(["status", rid], tmp_path)["ledger_count"]

    # drill into region → ledger grows
    seg = _run(["segments", "--run", rid, "--dimension", "region"], tmp_path)
    assert seg["status"] == "success" and seg["new_entries"]
    count_after = _run(["status", rid], tmp_path)["ledger_count"]
    assert count_after > count_before

    # re-synthesize on the enriched ledger, then re-render
    assert _run(["synth", "--run", rid, "was it SEA?"], tmp_path)["status"] == "success"
    rep = _run(["report", "--run", rid], tmp_path)
    assert rep["status"] == "success"
    assert os.path.exists(rep["report_path"])
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/cli/test_drilldown_e2e.py -v`
Expected: PASS. If a step errors, inspect the response `error`/activity and fix the real cause (do not weaken assertions).

- [ ] **Step 3: Real console smoke**

```bash
uv pip install -e . --python .venv/bin/python
.venv/bin/gaa --help        # confirm: analyze step status jobs doctor config onboard profile detect segments market signals synth report
```
Expected: `--help` lists all 14 subcommands including the six new primitives. No tracebacks.

- [ ] **Step 4: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → green; record the count.
```bash
git add tests/cli/test_drilldown_e2e.py
git commit -m "test: drilldown e2e (analyze→segments→synth→report)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review (against the spec)

- **Six Tier-2 primitives (spec §6):** `detect` (Task 3), `segments` (Task 2, with `--dimension` via Task 1), `market` (Task 3), `signals` (Task 3), `synth` (Task 4), `report` (Task 5). ✓
- **"Reads the run's window/profile from job.json, appends provenance-tagged findings, prints them" (spec §6):** `load_run_context` + `run_module_primitive` — Task 2. New entries carry the module's own provenance (`source_type`/`strength`); the helper reports only the delta. ✓
- **Follow-up synth re-runs citation validation (spec §6 honesty note):** `cmd_synth` applies `validate_citations` — Task 4. ✓
- **Concurrency:** every primitive mutates under `ctx.runs.locked(run_id)` and re-reads inside the lock, consistent with `step`. ✓
- **Trust chain intact:** modules write the ledger; the dossier (`report`) is built only from a validated `hypothesis`. ✓
- **Deferred (documented):** `signals --query`. Not built; noted in scope.
- **Type/interface consistency:** all primitive functions take `(ctx, args)` and return `{status, …}`; `run_module_primitive` returns `{status, run_id, module, new_entries, ledger_count}`; `GaaContext` gains `synth`/`signals` used by `cmd_synth`/`cmd_signals`; `SegmentDecomposition(dims=…)` matches Task 1's new signature; `cmd_synth` uses `ctx.pipeline.n_samples` (a public attribute set in `build_context`).

No placeholders or undefined references.

## After Plan 2b → Plan 2c

`gaa.lab` (Tier 3 read-only data API + `scratch/` + `adhoc:` evidence capped at Moderate) and tool promotion (Tier 2.5: `gaa tools promote|run|list|show|remove|sync-docs|export|import`, md5-frozen `data/tools/` registry). Then Plans 3 (OpenClaw install) and 4 (frontend + proxy).

---

## As-built notes (deviations recorded during execution)

Plan 2b was executed via subagent-driven development with a final review (APPROVE_WITH_MINORS, all addressed). Deviations from the task text above:

1. **Drilldown primitives persist context mutations, not just the ledger (review fix).** `run_module_primitive` now writes `metric/start/end/direction/changepoint` from the (possibly mutated) `AnalysisContext` back into `run.state` before saving — so `gaa detect --run R --metric revenue` re-points the run and a later `gaa synth`/`gaa report` renders the metric the new evidence is about. Without this, evidence and dossier could diverge (would have surfaced in Plans 3/4). No-op for the read-only modules (segments/market/signals).
2. **`gaa report` clears a stale `run.error` when marking the run done (review fix)** — a run that errored mid-render but now has a complete re-rendered dossier ends in a coherent `done`/no-error state.
3. **`gaa signals --query`** deferred (noted in scope) — 2b ships `gaa signals --run <id>` against the configured signals source.

Final state: **225 tests passing**; `gaa` surface is the 14 subcommands `analyze/step/status/jobs/doctor/config/onboard/profile/segments/detect/market/signals/synth/report`; the follow-up loop (analyze→done → drill into a dimension → re-synthesize on the enriched ledger → re-render) is verified end-to-end. Trust chain intact: `synth` re-runs the citation validator; `report` builds only from a validated hypothesis.
