# Game Attribution Agent — Plan 2: Analysis Engine

> ⚠️ **RECONCILED BY [Plan 0 — AgentBase + LangGraph Integration](2026-06-11-game-attribution-agent-plan-0-agentbase-langgraph-integration.md).** This plan's engine components (Tasks 1–9, 11–13: hypothesis/ledger schema, confidence, MetricsStore, the 4 modules, source interfaces+fixtures, synthesizer, validator, planner+markdown) **remain valid as written** — the `AttributionEngine` stays a **library the LangGraph nodes call.** **Superseded:** Task 10 (anthropic LLM client → MaaS `ChatOpenAI` client; the `LLM` protocol + `FakeLLM` are unchanged). **Amended:** Tasks 13–14 (no FastAPI `/analyze` route — the graph in Plan 0 invokes the engine). See Plan 0's supersession map.

> 🔬 **UPGRADED BY [Plan 2A — Analytics Rigor](2026-06-11-game-attribution-agent-plan-2a-analytics-rigor.md).** Tasks **6 (Anomaly)**, **7 (Segment)**, **8 (Market)** here implement *naive-delta* versions — Plan 2A **replaces** them with research-backed methods (Adtributor, CausalImpact-style counterfactual, change-point + STL) and adds a self-consistency abstention gate + `n_samples` engine wiring. Build the Plan 2A versions; the naive ones here are kept only as reference. Tasks 1–5, 9, 11–13 are unchanged.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a `GameProfile` + a natural-language query into a fully-formed `AttributionHypothesis` (JSON) — orchestrator → 4 analysis modules → Evidence Ledger → LLM synthesizer with rule-based dual confidence and a citation validator — and serve it from `POST /analyze`.

**Architecture:** Builds on Plan 1 (`GameProfile`, canonical schema, `ProfileStore`, adapters, FastAPI app). Internal metrics are loaded from a `MetricsStore` (parquet per game). Each analysis module reads an `AnalysisContext` and emits `LedgerEntry` objects into an `EvidenceLedger`. External modules read through `BenchmarkSource` / `SignalsSource` **interfaces** that are backed by seeded fixtures here (Plan 3 swaps in the live crawler behind the same interfaces). The `Synthesizer` (LLM, injectable for tests) composes the narrative and proposes which ledger ids support each claim; `evidence_quality` is **computed by rule**, not by the LLM; a `Validator` drops claims whose citations don't exist. The HTML `html` field stays minimal here (`markdown_summary` is real); Plan 3 renders the rich report.

**Tech Stack:** Python 3.11, Pydantic v2, pandas, numpy, anthropic SDK + httpx (MaaS fallback), pytest.

**Dependency note:** Requires Plan 1 merged. External live data is Plan 3 — modules here depend only on the source *interfaces* + fixtures, so the engine is fully testable offline.

---

### Task 1: Confidence + Hypothesis schema

**Files:**
- Create: `src/gaa/schema/confidence.py`
- Create: `src/gaa/schema/hypothesis.py`
- Test: `tests/schema/test_hypothesis.py`

- [ ] **Step 1: Write the failing test**

`tests/schema/test_hypothesis.py`:
```python
from gaa.schema.confidence import Confidence, LIKELIHOODS, EVIDENCE_QUALITIES
from gaa.schema.hypothesis import Cause, Scenario, Risk, AttributionHypothesis

def test_enums():
    assert LIKELIHOODS == ("Very likely", "Likely", "Possible", "Unlikely")
    assert EVIDENCE_QUALITIES == ("Strong", "Moderate", "Weak")

def test_confidence_validates_members():
    c = Confidence(likelihood="Likely", evidence_quality="Moderate")
    assert c.likelihood == "Likely"
    import pytest
    with pytest.raises(ValueError):
        Confidence(likelihood="Maybe", evidence_quality="Moderate")

def test_hypothesis_roundtrip():
    h = AttributionHypothesis(
        main_story="x",
        confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes={"internal": [Cause(claim="a", evidence_ids=["L1"],
                                   likelihood="Likely", evidence_quality="Strong")],
                "market": []},
        scenarios=[Scenario(description="s", likelihood="Possible",
                            evidence_quality="Weak", signals_to_watch=["x"])],
        risks=[Risk(description="r", likelihood="Possible", evidence_quality="Weak")],
        evidence=[],
        assumptions_and_gaps=["no UA data"],
    )
    assert AttributionHypothesis(**h.model_dump()).main_story == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schema/test_hypothesis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.schema.confidence'`.

- [ ] **Step 3: Write `src/gaa/schema/confidence.py`**

```python
from typing import Literal
from pydantic import BaseModel

LIKELIHOODS = ("Very likely", "Likely", "Possible", "Unlikely")
EVIDENCE_QUALITIES = ("Strong", "Moderate", "Weak")

Likelihood = Literal["Very likely", "Likely", "Possible", "Unlikely"]
EvidenceQuality = Literal["Strong", "Moderate", "Weak"]


class Confidence(BaseModel):
    likelihood: Likelihood
    evidence_quality: EvidenceQuality
```

- [ ] **Step 4: Write `src/gaa/schema/hypothesis.py`**

```python
from pydantic import BaseModel
from gaa.schema.confidence import Confidence, Likelihood, EvidenceQuality
from gaa.schema.ledger import LedgerEntry


class Cause(BaseModel):
    claim: str
    evidence_ids: list[str]
    likelihood: Likelihood
    evidence_quality: EvidenceQuality


class Scenario(BaseModel):
    description: str
    likelihood: Likelihood
    evidence_quality: EvidenceQuality
    signals_to_watch: list[str] = []


class Risk(BaseModel):
    description: str
    likelihood: Likelihood
    evidence_quality: EvidenceQuality


class Causes(BaseModel):
    internal: list[Cause] = []
    market: list[Cause] = []


class AttributionHypothesis(BaseModel):
    main_story: str
    confidence: Confidence
    causes: Causes
    scenarios: list[Scenario] = []
    risks: list[Risk] = []
    evidence: list[LedgerEntry] = []
    assumptions_and_gaps: list[str] = []
```

> Note: `Causes` accepts a dict in the test via `causes={"internal": [...], "market": []}` because Pydantic coerces dicts to the model. `LedgerEntry` is defined in Task 2 — implement Task 2 first if running tests strictly in order, or create `schema/ledger.py` now (its code is in Task 2 Step 3).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/schema/test_hypothesis.py -v` (after Task 2's `ledger.py` exists)
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/schema/confidence.py src/gaa/schema/hypothesis.py tests/schema/test_hypothesis.py
git commit -m "feat: confidence + attribution hypothesis schema"
```

---

### Task 2: Evidence Ledger

**Files:**
- Create: `src/gaa/schema/ledger.py`
- Test: `tests/schema/test_ledger.py`

- [ ] **Step 1: Write the failing test**

`tests/schema/test_ledger.py`:
```python
from gaa.schema.ledger import LedgerEntry, EvidenceLedger

def test_add_assigns_sequential_ids():
    led = EvidenceLedger()
    i1 = led.add(module="anomaly", claim="dau -25%", value="-0.25",
                 source="internal:dau", source_type="internal", strength="high",
                 timeframe="2026-05")
    i2 = led.add(module="market", claim="genre flat", value="-0.03",
                 source="romonitor", source_type="external", strength="med")
    assert i1 == "L1" and i2 == "L2"
    assert led.get("L1").claim == "dau -25%"
    assert len(led.all()) == 2

def test_by_ids():
    led = EvidenceLedger()
    led.add(module="m", claim="c", value="v", source="s",
            source_type="derived", strength="low")
    assert [e.id for e in led.by_ids(["L1", "Lx"])] == ["L1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schema/test_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.schema.ledger'`.

- [ ] **Step 3: Write implementation**

`src/gaa/schema/ledger.py`:
```python
from typing import Literal, Optional
from pydantic import BaseModel

SourceType = Literal["internal", "external", "derived"]
Strength = Literal["high", "med", "low"]


class LedgerEntry(BaseModel):
    id: str
    module: str
    claim: str
    value: str
    source: str
    source_type: SourceType
    strength: Strength
    timeframe: Optional[str] = None


class EvidenceLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def add(self, *, module: str, claim: str, value: str, source: str,
            source_type: SourceType, strength: Strength,
            timeframe: Optional[str] = None) -> str:
        eid = f"L{len(self._entries) + 1}"
        self._entries.append(LedgerEntry(
            id=eid, module=module, claim=claim, value=value, source=source,
            source_type=source_type, strength=strength, timeframe=timeframe))
        return eid

    def get(self, eid: str) -> Optional[LedgerEntry]:
        return next((e for e in self._entries if e.id == eid), None)

    def by_ids(self, ids: list[str]) -> list[LedgerEntry]:
        idset = set(ids)
        return [e for e in self._entries if e.id in idset]

    def all(self) -> list[LedgerEntry]:
        return list(self._entries)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schema/test_ledger.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/schema/ledger.py tests/schema/test_ledger.py
git commit -m "feat: evidence ledger"
```

---

### Task 3: Rule-based evidence-quality computation

**Files:**
- Create: `src/gaa/confidence.py`
- Test: `tests/test_confidence.py`

- [ ] **Step 1: Write the failing test**

`tests/test_confidence.py`:
```python
from gaa.schema.ledger import LedgerEntry
from gaa.confidence import evidence_quality

def _e(stype, strength):
    return LedgerEntry(id="L", module="m", claim="c", value="v",
                       source="s", source_type=stype, strength=strength)

def test_empty_is_weak():
    assert evidence_quality([]) == "Weak"

def test_internal_and_external_agreement_is_strong():
    entries = [_e("internal", "high"), _e("external", "high"), _e("derived", "med")]
    assert evidence_quality(entries) == "Strong"

def test_single_medium_internal_is_weak_or_moderate():
    assert evidence_quality([_e("internal", "med")]) == "Weak"

def test_two_sources_one_high_is_moderate():
    assert evidence_quality([_e("internal", "high"), _e("derived", "low")]) == "Moderate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_confidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.confidence'`.

- [ ] **Step 3: Write implementation**

`src/gaa/confidence.py`:
```python
from gaa.schema.ledger import LedgerEntry
from gaa.schema.confidence import EvidenceQuality


def evidence_quality(entries: list[LedgerEntry]) -> EvidenceQuality:
    """Rule-based analytical confidence from supporting ledger entries.

    Score = #entries
          + 2 if internal AND external both corroborate
          + 1 if any entry has high strength
    Strong >= 4, Moderate >= 2, else Weak.
    """
    if not entries:
        return "Weak"
    n = len(entries)
    types = {e.source_type for e in entries}
    has_both = "internal" in types and "external" in types
    has_high = any(e.strength == "high" for e in entries)
    score = n + (2 if has_both else 0) + (1 if has_high else 0)
    if score >= 4:
        return "Strong"
    if score >= 2:
        return "Moderate"
    return "Weak"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_confidence.py -v`
Expected: PASS (4 passed). (`single medium internal`: score=1 → Weak ✓; `two sources one high`: score=2+1=3 → Moderate ✓.)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/confidence.py tests/test_confidence.py
git commit -m "feat: rule-based evidence-quality computation"
```

---

### Task 4: MetricsStore (parquet per game)

**Files:**
- Create: `src/gaa/store/metrics_store.py`
- Test: `tests/store/test_metrics_store.py`

- [ ] **Step 1: Write the failing test**

`tests/store/test_metrics_store.py`:
```python
import pandas as pd
from gaa.store.metrics_store import MetricsStore
from gaa.schema.canonical import validate_canonical

def _canon():
    return validate_canonical(pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-02"]),
        "metric": ["dau", "dau"], "value": [100.0, 90.0],
    }))

def test_save_and_load(tmp_path):
    store = MetricsStore(str(tmp_path))
    store.save("MyGame", _canon())
    df = store.load("MyGame")
    assert len(df) == 2 and set(df["metric"]) == {"dau"}

def test_load_missing_raises(tmp_path):
    store = MetricsStore(str(tmp_path))
    import pytest
    with pytest.raises(FileNotFoundError):
        store.load("ghost")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/store/test_metrics_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/store/metrics_store.py`:
```python
import os
import re
import pandas as pd
from gaa.schema.canonical import validate_canonical


class MetricsStore:
    def __init__(self, root: str) -> None:
        self._root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, game: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", game)
        return os.path.join(self._root, f"{safe}.parquet")

    def save(self, game: str, df: pd.DataFrame) -> None:
        validate_canonical(df).to_parquet(self._path(game), index=False)

    def load(self, game: str) -> pd.DataFrame:
        path = self._path(game)
        if not os.path.exists(path):
            raise FileNotFoundError(f"no metrics for game '{game}'")
        return validate_canonical(pd.read_parquet(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/store/test_metrics_store.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/store/metrics_store.py tests/store/test_metrics_store.py
git commit -m "feat: parquet MetricsStore per game"
```

---

### Task 5: AnalysisContext + Module base + external source interfaces

**Files:**
- Create: `src/gaa/modules/__init__.py` (empty)
- Create: `src/gaa/modules/base.py`
- Create: `src/gaa/sources/__init__.py` (empty)
- Create: `src/gaa/sources/base.py`
- Create: `src/gaa/sources/fixtures.py`
- Test: `tests/sources/test_fixtures.py`
- Create: `tests/sources/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/sources/test_fixtures.py`:
```python
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource

def test_benchmark_returns_genre_series():
    b = FixtureBenchmarkSource(genre_index={"2026-05-01": 100.0, "2026-05-03": 98.0})
    s = b.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert s["2026-05-03"] == 98.0

def test_signals_returns_events():
    src = FixtureSignalsSource(events=[
        {"date": "2026-04-28", "title": "Competitor Y soft-launch", "kind": "competitor",
         "url": "http://x", "sentiment": -0.2}])
    evs = src.events("MyGame", "survival", "2026-04-01", "2026-05-31")
    assert evs[0]["kind"] == "competitor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_fixtures.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/gaa/modules/base.py`**

```python
from dataclasses import dataclass, field
from typing import Optional, Protocol
import pandas as pd
from gaa.schema.profile import GameProfile
from gaa.schema.ledger import EvidenceLedger


@dataclass
class AnalysisContext:
    profile: GameProfile
    metrics: pd.DataFrame            # canonical long-format
    query: str
    metric: Optional[str] = None     # e.g. "dau"; None triggers scan mode
    start: Optional[str] = None      # ISO date
    end: Optional[str] = None
    direction: Optional[str] = None  # "down" | "up"
    extras: dict = field(default_factory=dict)


class AnalysisModule(Protocol):
    name: str
    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        """Append findings to the ledger. Never raise on missing data —
        record a derived 'data gap' entry instead."""
        ...
```

- [ ] **Step 4: Write `src/gaa/sources/base.py`**

```python
from typing import Protocol


class BenchmarkSource(Protocol):
    def genre_trend(self, genre: str, start: str, end: str) -> dict[str, float]:
        """date(ISO) -> indexed genre metric (100 = window start)."""
        ...


class SignalsSource(Protocol):
    def events(self, game: str, genre: str, start: str, end: str) -> list[dict]:
        """Each: {date, title, kind, url, sentiment}."""
        ...
```

- [ ] **Step 5: Write `src/gaa/sources/fixtures.py`**

```python
from gaa.sources.base import BenchmarkSource, SignalsSource


class FixtureBenchmarkSource:
    def __init__(self, genre_index: dict[str, float] | None = None) -> None:
        self._idx = genre_index or {}

    def genre_trend(self, genre: str, start: str, end: str) -> dict[str, float]:
        return {d: v for d, v in self._idx.items() if start <= d <= end}


class FixtureSignalsSource:
    def __init__(self, events: list[dict] | None = None) -> None:
        self._events = events or []

    def events(self, game: str, genre: str, start: str, end: str) -> list[dict]:
        return [e for e in self._events if start <= e["date"] <= end]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/sources/test_fixtures.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add src/gaa/modules/__init__.py src/gaa/modules/base.py src/gaa/sources/ tests/sources/
git commit -m "feat: analysis context, module protocol, external source interfaces + fixtures"
```

---

### Task 6: Internal · Anomaly Detection module (with scan mode)

**Files:**
- Create: `src/gaa/modules/anomaly.py`
- Test: `tests/modules/test_anomaly.py`
- Create: `tests/modules/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/modules/test_anomaly.py`:
```python
import pandas as pd
from gaa.modules.anomaly import AnomalyDetection
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.profile import GameProfile, ColumnMapping

def _ctx(metric=None):
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"] * 1),
        "metric": ["dau", "dau", "dau"],
        "value": [1000.0, 980.0, 600.0],
        "platform": [None, None, None], "region": [None]*3, "version": [None]*3,
        "cohort": [None]*3, "device": [None]*3, "source": [None]*3,
    })
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="what happened", metric=metric)

def test_quantifies_specified_metric_drop():
    led = EvidenceLedger()
    AnomalyDetection().run(_ctx(metric="dau"), led)
    entries = led.all()
    assert any("dau" in e.claim and e.source_type == "internal" for e in entries)
    drop = next(e for e in entries if e.module == "anomaly")
    assert "-" in drop.value  # negative change quantified

def test_scan_mode_picks_most_salient_metric():
    led = EvidenceLedger()
    AnomalyDetection().run(_ctx(metric=None), led)  # scan mode
    assert any(e.module == "anomaly" for e in led.all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/test_anomaly.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/modules/anomaly.py`:
```python
import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger


def _series(df: pd.DataFrame, metric: str) -> pd.Series:
    sub = df[df["metric"] == metric].groupby("date")["value"].sum().sort_index()
    return sub


def _pct_change_window(s: pd.Series) -> float:
    if len(s) < 2 or s.iloc[0] == 0:
        return 0.0
    return (s.iloc[-1] - s.iloc[0]) / abs(s.iloc[0])


class AnomalyDetection:
    name = "anomaly"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        metrics = list(ctx.metrics["metric"].unique())
        if not metrics:
            ledger.add(module=self.name, claim="no internal metrics available",
                       value="n/a", source="internal", source_type="derived",
                       strength="low")
            return

        if ctx.metric:
            target = ctx.metric
        else:  # scan mode: largest absolute % move
            target = max(metrics, key=lambda m: abs(_pct_change_window(_series(ctx.metrics, m))))
            ctx.metric = target

        s = _series(ctx.metrics, target)
        change = _pct_change_window(s)
        ctx.direction = "down" if change < 0 else "up"
        ctx.start = ctx.start or str(s.index.min().date())
        ctx.end = ctx.end or str(s.index.max().date())
        ledger.add(
            module=self.name,
            claim=f"{target} changed {change:+.0%} over window",
            value=f"{change:+.2%}",
            source=f"internal:{target}",
            source_type="internal",
            strength="high" if abs(change) >= 0.1 else "med",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/test_anomaly.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/modules/anomaly.py tests/modules/
git commit -m "feat: anomaly detection module with scan mode"
```

---

### Task 7: Internal · Segment Decomposition module

**Files:**
- Create: `src/gaa/modules/segment.py`
- Test: `tests/modules/test_segment.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/test_segment.py`:
```python
import pandas as pd
from gaa.modules.segment import SegmentDecomposition
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.profile import GameProfile, ColumnMapping

def _ctx():
    rows = []
    for d, sea, na in [("2026-05-01", 1000, 800), ("2026-05-03", 400, 770)]:
        rows.append({"date": d, "metric": "dau", "value": float(sea), "region": "SEA"})
        rows.append({"date": d, "metric": "dau", "value": float(na), "region": "NA"})
    df = pd.DataFrame(rows)
    for c in ["platform", "version", "cohort", "device", "source"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-05-01", end="2026-05-03", direction="down")

def test_identifies_dominant_segment():
    led = EvidenceLedger()
    SegmentDecomposition().run(_ctx(), led)
    claims = " ".join(e.claim for e in led.all())
    assert "SEA" in claims  # SEA fell 1000->400, NA barely moved
    assert any(e.module == "segment" and e.source_type == "internal" for e in led.all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/test_segment.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/modules/segment.py`:
```python
import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger

DIMS = ["version", "region", "platform", "cohort", "device", "source"]


class SegmentDecomposition:
    name = "segment"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not ctx.metric or not ctx.start or not ctx.end:
            return
        df = ctx.metrics[ctx.metrics["metric"] == ctx.metric]
        start_ts, end_ts = pd.Timestamp(ctx.start), pd.Timestamp(ctx.end)

        best = None  # (dim, value, contribution)
        for dim in DIMS:
            if df[dim].isna().all():
                continue
            grouped = df.groupby([dim, "date"])["value"].sum().reset_index()
            for seg, g in grouped.groupby(dim):
                g = g.set_index("date")["value"]
                if start_ts not in g.index or end_ts not in g.index:
                    continue
                delta = g[end_ts] - g[start_ts]
                if best is None or abs(delta) > abs(best[2]):
                    best = (dim, seg, delta)

        if best is None:
            ledger.add(module=self.name,
                       claim="no segment dimensions available to decompose",
                       value="n/a", source="internal", source_type="derived",
                       strength="low")
            return

        dim, seg, delta = best
        ledger.add(
            module=self.name,
            claim=f"change concentrated in {dim}={seg} (Δ {delta:+.0f})",
            value=f"{delta:+.0f}",
            source=f"internal:{ctx.metric} by {dim}",
            source_type="internal",
            strength="high",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/test_segment.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/modules/segment.py tests/modules/test_segment.py
git commit -m "feat: segment decomposition module"
```

---

### Task 8: External · Market Benchmark module

**Files:**
- Create: `src/gaa/modules/market_benchmark.py`
- Test: `tests/modules/test_market_benchmark.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/test_market_benchmark.py`:
```python
import pandas as pd
from gaa.modules.market_benchmark import MarketBenchmark
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.fixtures import FixtureBenchmarkSource
from gaa.schema.profile import GameProfile, ColumnMapping

def _ctx():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-05-01", end="2026-05-03", direction="down")

def test_flags_underperformance_vs_flat_genre():
    # game -40%, genre roughly flat -> "it's us, not the market"
    bench = FixtureBenchmarkSource(genre_index={"2026-05-01": 100.0, "2026-05-03": 98.0})
    led = EvidenceLedger()
    MarketBenchmark(bench).run(_ctx(), led)
    entries = [e for e in led.all() if e.module == "market"]
    assert entries and entries[0].source_type == "external"
    assert "genre" in entries[0].claim.lower()

def test_records_gap_when_no_benchmark():
    led = EvidenceLedger()
    MarketBenchmark(FixtureBenchmarkSource(genre_index={})).run(_ctx(), led)
    assert any(e.strength == "low" and e.source_type == "derived" for e in led.all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/test_market_benchmark.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/modules/market_benchmark.py`:
```python
import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.base import BenchmarkSource


class MarketBenchmark:
    name = "market"

    def __init__(self, source: BenchmarkSource) -> None:
        self._source = source

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.metric and ctx.start and ctx.end):
            return
        trend = self._source.genre_trend(ctx.profile.genre, ctx.start, ctx.end)
        if len(trend) < 2:
            ledger.add(module=self.name,
                       claim="no genre benchmark available for this window",
                       value="n/a", source="benchmark", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        keys = sorted(trend)
        genre_change = (trend[keys[-1]] - trend[keys[0]]) / abs(trend[keys[0]])

        s = ctx.metrics[ctx.metrics["metric"] == ctx.metric].groupby("date")["value"].sum().sort_index()
        game_change = (s.iloc[-1] - s.iloc[0]) / abs(s.iloc[0]) if len(s) >= 2 and s.iloc[0] else 0.0

        gap = game_change - genre_change
        verdict = "underperforming the genre" if gap < -0.05 else (
            "in line with the genre" if abs(gap) <= 0.05 else "outperforming the genre")
        ledger.add(
            module=self.name,
            claim=f"genre moved {genre_change:+.0%} vs game {game_change:+.0%} → {verdict}",
            value=f"genre {genre_change:+.2%}; game {game_change:+.2%}",
            source="benchmark:genre_index",
            source_type="external",
            strength="med",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/test_market_benchmark.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/modules/market_benchmark.py tests/modules/test_market_benchmark.py
git commit -m "feat: market benchmark module (internal-vs-genre)"
```

---

### Task 9: External · Competitor & Event Signals module

**Files:**
- Create: `src/gaa/modules/competitor_signals.py`
- Test: `tests/modules/test_competitor_signals.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/test_competitor_signals.py`:
```python
import pandas as pd
from gaa.modules.competitor_signals import CompetitorSignals
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.fixtures import FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping

def _ctx():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01"]), "metric": ["dau"], "value": [1.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    prof = GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-04-01", end="2026-05-31", direction="down")

def test_logs_events_as_external_entries():
    src = FixtureSignalsSource(events=[
        {"date": "2026-04-28", "title": "Competitor Y soft-launch", "kind": "competitor",
         "url": "http://x", "sentiment": -0.3},
        {"date": "2026-05-04", "title": "v3.2 update notes", "kind": "patch",
         "url": "http://p", "sentiment": 0.0}])
    led = EvidenceLedger()
    CompetitorSignals(src).run(_ctx(), led)
    ext = [e for e in led.all() if e.module == "competitor" and e.source_type == "external"]
    assert len(ext) == 2
    assert any("Competitor Y" in e.claim for e in ext)

def test_no_events_records_gap():
    led = EvidenceLedger()
    CompetitorSignals(FixtureSignalsSource(events=[])).run(_ctx(), led)
    assert any(e.source_type == "derived" and e.strength == "low" for e in led.all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/test_competitor_signals.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/modules/competitor_signals.py`:
```python
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.base import SignalsSource

_STRENGTH_BY_KIND = {"patch": "high", "competitor": "med", "news": "med", "social": "low"}


class CompetitorSignals:
    name = "competitor"

    def __init__(self, source: SignalsSource) -> None:
        self._source = source

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.start and ctx.end):
            return
        events = self._source.events(ctx.profile.name, ctx.profile.genre, ctx.start, ctx.end)
        if not events:
            ledger.add(module=self.name,
                       claim="no external competitor/event signals found in window",
                       value="0 events", source="signals", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        for ev in events:
            ledger.add(
                module=self.name,
                claim=f"{ev['kind']}: {ev['title']}",
                value=f"sentiment {ev.get('sentiment', 0):+.2f}",
                source=ev.get("url", "signals"),
                source_type="external",
                strength=_STRENGTH_BY_KIND.get(ev["kind"], "low"),
                timeframe=ev["date"],
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/test_competitor_signals.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/modules/competitor_signals.py tests/modules/test_competitor_signals.py
git commit -m "feat: competitor & event signals module"
```

---

### Task 10: LLM client (Claude + MaaS fallback) + FakeLLM

**Files:**
- Create: `src/gaa/llm/__init__.py` (empty)
- Create: `src/gaa/llm/client.py`
- Test: `tests/llm/test_client.py`
- Create: `tests/llm/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/llm/test_client.py`:
```python
from gaa.llm.client import FakeLLM, LLMClient

def test_fake_llm_returns_preset():
    llm = FakeLLM({"main_story": "x"})
    assert llm.complete_json("sys", "user")["main_story"] == "x"

def test_llmclient_protocol_shape():
    # LLMClient must expose complete_json(system, user) -> dict
    assert hasattr(LLMClient, "complete_json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/llm/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/llm/client.py`:
```python
import json
from typing import Protocol, Optional
from gaa.config import Settings


class LLM(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class FakeLLM:
    """Test double: returns a preset dict regardless of input."""
    def __init__(self, preset: dict) -> None:
        self._preset = preset

    def complete_json(self, system: str, user: str) -> dict:
        return dict(self._preset)


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start:end + 1])


class LLMClient:
    """Claude primary with MaaS (OpenAI-compatible) fallback. JSON-mode via prompt."""
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._s = settings or Settings()

    def complete_json(self, system: str, user: str) -> dict:
        try:
            return self._claude(system, user)
        except Exception:
            return self._maas(system, user)

    def _claude(self, system: str, user: str) -> dict:
        import anthropic
        client = anthropic.Anthropic(api_key=self._s.anthropic_api_key)
        msg = client.messages.create(
            model=self._s.model, max_tokens=2000,
            system=system + "\nRespond ONLY with a single valid JSON object.",
            messages=[{"role": "user", "content": user}],
        )
        return _extract_json(msg.content[0].text)

    def _maas(self, system: str, user: str) -> dict:
        import httpx
        r = httpx.post(
            f"{self._s.maas_base_url}/chat/completions",
            json={"model": self._s.maas_fallback_model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=60,
        )
        r.raise_for_status()
        return _extract_json(r.json()["choices"][0]["message"]["content"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/llm/test_client.py -v`
Expected: PASS (2 passed). (Real Claude/MaaS calls are not exercised in unit tests; the synthesizer is tested with `FakeLLM`.)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/llm/ tests/llm/
git commit -m "feat: LLM client (Claude + MaaS fallback) + FakeLLM test double"
```

---

### Task 11: Synthesizer (LLM → hypothesis, rule-based evidence quality)

**Files:**
- Create: `src/gaa/synth/__init__.py` (empty)
- Create: `src/gaa/synth/synthesizer.py`
- Test: `tests/synth/test_synthesizer.py`
- Create: `tests/synth/__init__.py` (empty)

The LLM proposes `main_story`, `causes` (claims + `evidence_ids` + `likelihood`), `scenarios`, `risks`, `assumptions_and_gaps`. The synthesizer **ignores any evidence_quality the LLM emits** and computes it from the cited ledger entries; it attaches the full ledger as `evidence` and derives the headline confidence.

- [ ] **Step 1: Write the failing test**

`tests/synth/test_synthesizer.py`:
```python
from gaa.synth.synthesizer import Synthesizer
from gaa.llm.client import FakeLLM
from gaa.schema.ledger import EvidenceLedger

def _ledger():
    led = EvidenceLedger()
    led.add(module="anomaly", claim="dau -40%", value="-0.40", source="internal:dau",
            source_type="internal", strength="high")
    led.add(module="market", claim="genre flat", value="-0.03", source="benchmark",
            source_type="external", strength="med")
    return led

def test_computes_evidence_quality_from_citations():
    preset = {
        "main_story": "Mostly internal.",
        "causes": {
            "internal": [{"claim": "v3.2 hurt retention", "evidence_ids": ["L1"],
                          "likelihood": "Likely"}],
            "market": [{"claim": "genre flat rules out market", "evidence_ids": ["L1", "L2"],
                        "likelihood": "Possible"}],
        },
        "scenarios": [{"description": "hotfix recovers", "likelihood": "Likely",
                       "evidence_ids": ["L1"], "signals_to_watch": ["D7 retention"]}],
        "risks": [{"description": "acq cut", "likelihood": "Possible", "evidence_ids": []}],
        "assumptions_and_gaps": ["no UA data"],
    }
    h = Synthesizer(FakeLLM(preset)).synthesize(_ledger(), query="why down?")
    # internal cause cites only L1 (internal,high) -> score 1+1=2 -> Moderate
    assert h.causes.internal[0].evidence_quality == "Moderate"
    # market cause cites L1+L2 (internal+external, one high) -> 2+2+1=5 -> Strong
    assert h.causes.market[0].evidence_quality == "Strong"
    assert len(h.evidence) == 2  # full ledger attached
    assert h.main_story == "Mostly internal."

def test_headline_confidence_present():
    h = Synthesizer(FakeLLM({
        "main_story": "x", "causes": {"internal": [], "market": []},
        "scenarios": [], "risks": [], "assumptions_and_gaps": []})).synthesize(_ledger(), "q")
    assert h.confidence.likelihood in ("Very likely", "Likely", "Possible", "Unlikely")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_synthesizer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/synth/synthesizer.py`:
```python
import json
from gaa.llm.client import LLM
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.hypothesis import (
    AttributionHypothesis, Cause, Scenario, Risk, Causes)
from gaa.schema.confidence import Confidence
from gaa.confidence import evidence_quality

SYSTEM = (
    "You are a game-data attribution analyst. Separate INTERNAL causes (the game's own "
    "updates, segments, monetization) from MARKET causes (genre-wide trends, seasonality, "
    "competitors). Present scenarios, never prescribe decisions. Ground every claim in the "
    "provided evidence ids; if evidence is thin, say so in assumptions_and_gaps. "
    "Return JSON with keys: main_story, causes{internal[],market[]}, scenarios[], risks[], "
    "assumptions_and_gaps[]. Each cause/scenario item has claim/description, evidence_ids[], "
    "and likelihood in {Very likely,Likely,Possible,Unlikely}. Do NOT output evidence_quality."
)


def _ledger_brief(ledger: EvidenceLedger) -> str:
    return "\n".join(
        f"{e.id} [{e.source_type}/{e.strength}] {e.claim} ({e.value}) src={e.source}"
        for e in ledger.all())


class Synthesizer:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def synthesize(self, ledger: EvidenceLedger, query: str) -> AttributionHypothesis:
        user = f"QUERY: {query}\n\nEVIDENCE LEDGER:\n{_ledger_brief(ledger)}"
        raw = self._llm.complete_json(SYSTEM, user)
        return self._assemble(raw, ledger)

    def _eq(self, ledger: EvidenceLedger, ids: list[str]) -> str:
        return evidence_quality(ledger.by_ids(ids))

    def _cause(self, ledger, item) -> Cause:
        ids = item.get("evidence_ids", [])
        return Cause(claim=item["claim"], evidence_ids=ids,
                     likelihood=item.get("likelihood", "Possible"),
                     evidence_quality=self._eq(ledger, ids))

    def _assemble(self, raw: dict, ledger: EvidenceLedger) -> AttributionHypothesis:
        causes_raw = raw.get("causes", {})
        internal = [self._cause(ledger, c) for c in causes_raw.get("internal", [])]
        market = [self._cause(ledger, c) for c in causes_raw.get("market", [])]
        scenarios = [
            Scenario(description=s["description"],
                     likelihood=s.get("likelihood", "Possible"),
                     evidence_quality=self._eq(ledger, s.get("evidence_ids", [])),
                     signals_to_watch=s.get("signals_to_watch", []))
            for s in raw.get("scenarios", [])]
        risks = [
            Risk(description=r["description"],
                 likelihood=r.get("likelihood", "Possible"),
                 evidence_quality=self._eq(ledger, r.get("evidence_ids", [])))
            for r in raw.get("risks", [])]

        # headline confidence = strongest internal cause, else overall ledger
        all_internal_ids = [i for c in internal for i in c.evidence_ids]
        headline_eq = self._eq(ledger, all_internal_ids) if all_internal_ids \
            else evidence_quality(ledger.all())
        headline_lk = internal[0].likelihood if internal else "Possible"

        return AttributionHypothesis(
            main_story=raw.get("main_story", ""),
            confidence=Confidence(likelihood=headline_lk, evidence_quality=headline_eq),
            causes=Causes(internal=internal, market=market),
            scenarios=scenarios, risks=risks,
            evidence=ledger.all(),
            assumptions_and_gaps=raw.get("assumptions_and_gaps", []),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/synth/test_synthesizer.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/synth/synthesizer.py tests/synth/
git commit -m "feat: synthesizer (LLM narrative + rule-based dual confidence)"
```

---

### Task 12: Citation validator

**Files:**
- Create: `src/gaa/synth/validator.py`
- Test: `tests/synth/test_validator.py`

- [ ] **Step 1: Write the failing test**

`tests/synth/test_validator.py`:
```python
from gaa.synth.validator import validate_citations
from gaa.schema.hypothesis import AttributionHypothesis, Cause, Scenario, Causes
from gaa.schema.confidence import Confidence
from gaa.schema.ledger import EvidenceLedger

def _ledger():
    led = EvidenceLedger()
    led.add(module="m", claim="c", value="v", source="s",
            source_type="internal", strength="high")  # L1
    return led

def _hyp():
    return AttributionHypothesis(
        main_story="x",
        confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(
            internal=[Cause(claim="ok", evidence_ids=["L1"], likelihood="Likely",
                            evidence_quality="Moderate"),
                      Cause(claim="bogus", evidence_ids=["L9"], likelihood="Likely",
                            evidence_quality="Weak")],
            market=[]),
        scenarios=[Scenario(description="ungrounded", likelihood="Possible",
                            evidence_quality="Weak", evidence_ids=["L9"], signals_to_watch=[])
                   if False else
                   Scenario(description="grounded", likelihood="Possible",
                            evidence_quality="Weak", signals_to_watch=[])],
        evidence=[], assumptions_and_gaps=[])

def test_drops_uncited_causes_and_notes_gap():
    led = _ledger()
    h = validate_citations(_hyp(), led)
    claims = [c.claim for c in h.causes.internal]
    assert "ok" in claims and "bogus" not in claims  # L9 doesn't exist -> dropped
    assert any("dropped" in g.lower() or "uncited" in g.lower()
               for g in h.assumptions_and_gaps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/synth/test_validator.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/synth/validator.py`:
```python
from gaa.schema.hypothesis import AttributionHypothesis, Cause
from gaa.schema.ledger import EvidenceLedger


def _valid(cause: Cause, valid_ids: set[str]) -> bool:
    return any(i in valid_ids for i in cause.evidence_ids)


def validate_citations(h: AttributionHypothesis, ledger: EvidenceLedger) -> AttributionHypothesis:
    valid_ids = {e.id for e in ledger.all()}
    dropped = 0

    kept_internal = [c for c in h.causes.internal if _valid(c, valid_ids)]
    kept_market = [c for c in h.causes.market if _valid(c, valid_ids)]
    dropped += (len(h.causes.internal) - len(kept_internal))
    dropped += (len(h.causes.market) - len(kept_market))
    h.causes.internal = kept_internal
    h.causes.market = kept_market

    # prune dangling evidence_ids that don't exist
    for c in h.causes.internal + h.causes.market:
        c.evidence_ids = [i for i in c.evidence_ids if i in valid_ids]

    if dropped:
        h.assumptions_and_gaps.append(
            f"{dropped} uncited claim(s) dropped for lacking ledger evidence.")
    return h
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/synth/test_validator.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/synth/validator.py tests/synth/test_validator.py
git commit -m "feat: citation validator (drop uncited claims, note gaps)"
```

---

### Task 13: Orchestrator (router + planner) + markdown summary

**Files:**
- Create: `src/gaa/orchestrator/__init__.py` (empty)
- Create: `src/gaa/orchestrator/planner.py`
- Create: `src/gaa/render/__init__.py` (empty)
- Create: `src/gaa/render/markdown.py`
- Test: `tests/orchestrator/test_planner.py`
- Create: `tests/orchestrator/__init__.py` (empty)

The router (setup vs analysis intent) lives in the API (Plan 3 adds onboarding); here the planner parses an analysis query into a partial context and the engine runs all four modules. `markdown.py` renders a short chat summary from a hypothesis.

- [ ] **Step 1: Write the failing test**

`tests/orchestrator/test_planner.py`:
```python
from gaa.orchestrator.planner import parse_query
from gaa.render.markdown import to_markdown
from gaa.schema.hypothesis import AttributionHypothesis, Causes
from gaa.schema.confidence import Confidence

def test_parse_detects_metric_and_direction():
    p = parse_query("why did revenue drop 25% in May?")
    assert p["metric"] == "revenue" and p["direction"] == "down"

def test_parse_open_ended_is_scan():
    p = parse_query("what's going on with my game?")
    assert p["metric"] is None  # scan mode

def test_markdown_includes_story_and_confidence():
    h = AttributionHypothesis(main_story="Mostly internal.",
                              confidence=Confidence(likelihood="Likely",
                                                    evidence_quality="Moderate"),
                              causes=Causes())
    md = to_markdown(h)
    assert "Mostly internal." in md and "Likely" in md and "Moderate" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/test_planner.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/gaa/orchestrator/planner.py`**

```python
import re

_METRICS = {
    "revenue": ["revenue", "rev", "earnings", "robux"],
    "dau": ["dau", "active users", "active player", "players"],
    "retention_d7": ["d7 retention", "retention", "retain"],
    "retention_d1": ["d1 retention"],
}


def parse_query(query: str) -> dict:
    q = query.lower()
    metric = None
    for canon, aliases in _METRICS.items():
        if any(a in q for a in aliases):
            metric = canon
            break
    direction = "down" if re.search(r"drop|fell|down|decline|crash|lost", q) else (
        "up" if re.search(r"spike|grew|rose|up|surge|gain", q) else None)
    return {"metric": metric, "direction": direction}
```

- [ ] **Step 4: Write `src/gaa/render/markdown.py`**

```python
from gaa.schema.hypothesis import AttributionHypothesis


def to_markdown(h: AttributionHypothesis) -> str:
    lines = [f"**{h.main_story}** — *{h.confidence.likelihood} · "
             f"{h.confidence.evidence_quality} evidence*", ""]
    if h.causes.internal:
        lines.append("**🔵 Internal**")
        for c in h.causes.internal:
            cites = " ".join(f"`{i}`" for i in c.evidence_ids)
            lines.append(f"- {c.claim} — *{c.likelihood} · {c.evidence_quality}* {cites}")
    if h.causes.market:
        lines.append("**🟠 Market**")
        for c in h.causes.market:
            cites = " ".join(f"`{i}`" for i in c.evidence_ids)
            lines.append(f"- {c.claim} — *{c.likelihood} · {c.evidence_quality}* {cites}")
    if h.scenarios:
        lines.append("\n**Next scenarios:**")
        for s in h.scenarios:
            lines.append(f"- {s.description} — *{s.likelihood} · {s.evidence_quality}*")
    if h.assumptions_and_gaps:
        lines.append("\n**Assumptions/gaps:** " + "; ".join(h.assumptions_and_gaps))
    return "\n".join(lines)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/orchestrator/test_planner.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/orchestrator/ src/gaa/render/__init__.py src/gaa/render/markdown.py tests/orchestrator/
git commit -m "feat: query planner + markdown summary renderer"
```

---

### Task 14: Engine assembly + wire `/analyze`

**Files:**
- Create: `src/gaa/engine.py`
- Modify: `src/gaa/api/app.py` (implement `/analyze`)
- Test: `tests/test_engine.py`
- Test: `tests/api/test_analyze.py`

- [ ] **Step 1: Write the failing engine test**

`tests/test_engine.py`:
```python
import pandas as pd
from gaa.engine import AttributionEngine
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping

def _profile():
    return GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="Date",
                                             metric_cols={"DAU": "dau"}, dim_cols={}))

def _metrics():
    rows = []
    for d, sea, na in [("2026-05-01", 1000, 800), ("2026-05-03", 400, 770)]:
        rows += [{"date": d, "metric": "dau", "value": float(sea), "region": "SEA"},
                 {"date": d, "metric": "dau", "value": float(na), "region": "NA"}]
    df = pd.DataFrame(rows)
    for c in ["platform", "version", "cohort", "device", "source"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    return df

def test_engine_produces_hypothesis_with_evidence():
    preset = {"main_story": "Mostly internal — SEA fell.",
              "causes": {"internal": [{"claim": "SEA collapse", "evidence_ids": ["L1", "L2"],
                                        "likelihood": "Likely"}],
                         "market": [{"claim": "genre flat", "evidence_ids": ["L3"],
                                     "likelihood": "Possible"}]},
              "scenarios": [], "risks": [], "assumptions_and_gaps": []}
    engine = AttributionEngine(
        llm=FakeLLM(preset),
        benchmark=FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 98.0}),
        signals=FixtureSignalsSource([{"date": "2026-05-02", "title": "patch v3.2",
                                       "kind": "patch", "url": "u", "sentiment": -0.1}]))
    h = engine.analyze(_profile(), _metrics(), "what happened to my game?")
    assert h.main_story.startswith("Mostly internal")
    assert len(h.evidence) >= 3  # anomaly + segment + market + signal
    assert h.causes.internal and h.causes.internal[0].evidence_quality in (
        "Strong", "Moderate", "Weak")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.engine'`.

- [ ] **Step 3: Write `src/gaa/engine.py`**

```python
import pandas as pd
from gaa.schema.profile import GameProfile
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.hypothesis import AttributionHypothesis
from gaa.modules.base import AnalysisContext
from gaa.modules.anomaly import AnomalyDetection
from gaa.modules.segment import SegmentDecomposition
from gaa.modules.market_benchmark import MarketBenchmark
from gaa.modules.competitor_signals import CompetitorSignals
from gaa.synth.synthesizer import Synthesizer
from gaa.synth.validator import validate_citations
from gaa.orchestrator.planner import parse_query
from gaa.llm.client import LLM
from gaa.sources.base import BenchmarkSource, SignalsSource


class AttributionEngine:
    def __init__(self, llm: LLM, benchmark: BenchmarkSource, signals: SignalsSource) -> None:
        self._synth = Synthesizer(llm)
        self._benchmark = benchmark
        self._signals = signals

    def analyze(self, profile: GameProfile, metrics: pd.DataFrame,
                query: str) -> AttributionHypothesis:
        parsed = parse_query(query)
        ctx = AnalysisContext(profile=profile, metrics=metrics, query=query,
                              metric=parsed["metric"], direction=parsed["direction"])
        ledger = EvidenceLedger()
        # order matters: anomaly resolves metric/window first (incl. scan mode)
        AnomalyDetection().run(ctx, ledger)
        SegmentDecomposition().run(ctx, ledger)
        MarketBenchmark(self._benchmark).run(ctx, ledger)
        CompetitorSignals(self._signals).run(ctx, ledger)
        hyp = self._synth.synthesize(ledger, query)
        return validate_citations(hyp, ledger)
```

- [ ] **Step 4: Run engine test**

Run: `pytest tests/test_engine.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Write the failing API test**

`tests/api/test_analyze.py`:
```python
import pandas as pd
from fastapi.testclient import TestClient
from gaa.api.app import create_app
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource

def _seed(tmp_path):
    ps = ProfileStore(str(tmp_path / "p.sqlite"))
    prof = GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={}))
    ps.save(prof); ps.set_active("MyGame")
    ms = MetricsStore(str(tmp_path / "metrics"))
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    ms.save("MyGame", df)
    return ps, ms

def test_analyze_returns_hypothesis_and_summary(tmp_path):
    ps, ms = _seed(tmp_path)
    app = create_app(
        profile_store=ps, metrics_store=ms,
        llm=FakeLLM({"main_story": "Mostly internal.",
                     "causes": {"internal": [{"claim": "dau fell", "evidence_ids": ["L1"],
                                              "likelihood": "Likely"}], "market": []},
                     "scenarios": [], "risks": [], "assumptions_and_gaps": []}),
        benchmark=FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
        signals=FixtureSignalsSource([]))
    r = TestClient(app).post("/analyze", json={"query": "why did dau drop?"})
    assert r.status_code == 200
    body = r.json()
    assert body["hypothesis"]["main_story"] == "Mostly internal."
    assert "Mostly internal." in body["markdown_summary"]
    assert "html" in body
```

- [ ] **Step 6: Update `create_app` to inject the engine and implement `/analyze`**

Modify `src/gaa/api/app.py`. Change the `create_app` signature and the `analyze` route:

```python
# add imports at top:
from gaa.store.metrics_store import MetricsStore
from gaa.engine import AttributionEngine
from gaa.render.markdown import to_markdown
from gaa.llm.client import LLMClient
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource

def create_app(db_path=None, profile_store=None, metrics_store=None,
               llm=None, benchmark=None, signals=None) -> FastAPI:
    settings = Settings()
    store = profile_store or ProfileStore(db_path or settings.db_path)
    metrics = metrics_store or MetricsStore(settings.cache_dir + "/metrics")
    engine = AttributionEngine(
        llm=llm or LLMClient(settings),
        benchmark=benchmark or FixtureBenchmarkSource({}),   # Plan 3 replaces with live source
        signals=signals or FixtureSignalsSource([]))
    app = FastAPI(title="Game Attribution Agent")
    # ... keep /health, /profiles, /ingest/preview unchanged ...

    @app.post("/analyze")
    def analyze(req: AnalyzeRequest):
        profile = store.get(req.game) if req.game else store.get_active()
        if profile is None:
            raise HTTPException(400, "no active GameProfile; create one via /profiles")
        try:
            df = metrics.load(profile.name)
        except FileNotFoundError:
            raise HTTPException(400, f"no metrics ingested for '{profile.name}'")
        h = engine.analyze(profile, df, req.query)
        return {"hypothesis": h.model_dump(),
                "markdown_summary": to_markdown(h),
                "html": ""}  # Plan 3 fills this with the rendered report
    return app
```

> Keep the existing `/health`, `/profiles`, `/ingest/preview` route bodies exactly as in Plan 1 — only the `create_app` signature, the engine wiring, and the `analyze` body change.

- [ ] **Step 7: Run all API + engine tests**

Run: `pytest tests/api/ tests/test_engine.py -v`
Expected: PASS (Plan 1 API tests still green; new `/analyze` test green).

- [ ] **Step 8: Run the full suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/gaa/engine.py src/gaa/api/app.py tests/test_engine.py tests/api/test_analyze.py
git commit -m "feat: attribution engine assembly + /analyze endpoint"
```

---

### Task 15: Run trace / observability (which module fired, what it wrote)

> **Why:** Observability is a first-class harness responsibility — the agent must record *every step* so a run can be debugged and, here, **shown**. This task gives each analysis run a structured `RunTrace`: per-module status (`ok` / `data_gap` / `error`), the ledger ids that module wrote, and its elapsed time. It doubles as demo material — Plan 3's report can render it as a "how this was computed" panel, and `/agentbase-monitor` logs stay at the container level while this is the *reasoning*-level trace.
>
> **Reconciliation:** The trace wraps `module.run()` from the *outside* and never touches module internals, so **Plan 2A's** research-backed modules (Adtributor / CausalImpact / change-point) trace unchanged as long as they keep the `name` + `run(ctx, ledger)` contract; if 2A adds a synthesis-level abstention step, append a final `TraceEvent(module="synthesis", …)` there. **Plan 0's** LangGraph nodes call `engine.analyze()` and get the trace on `hypothesis.trace` — surface it in graph state / logs.

**Files:**
- Create: `src/gaa/schema/trace.py`
- Modify: `src/gaa/schema/hypothesis.py` (add optional `trace` field)
- Modify: `src/gaa/engine.py` (populate trace; capture per-module errors instead of crashing the run)
- Test: `tests/test_trace.py`

- [ ] **Step 1: Write the failing test**

`tests/test_trace.py`:
```python
import pandas as pd
from gaa.engine import AttributionEngine
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping


def _profile():
    return GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="Date",
                                             metric_cols={"DAU": "dau"}, dim_cols={}))


def _metrics():
    rows = []
    for d, sea, na in [("2026-05-01", 1000, 800), ("2026-05-03", 400, 770)]:
        rows += [{"date": d, "metric": "dau", "value": float(sea), "region": "SEA"},
                 {"date": d, "metric": "dau", "value": float(na), "region": "NA"}]
    df = pd.DataFrame(rows)
    for c in ["platform", "version", "cohort", "device", "source"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    return df


def _engine(signals_events):
    preset = {"main_story": "x", "causes": {"internal": [], "market": []},
              "scenarios": [], "risks": [], "assumptions_and_gaps": []}
    return AttributionEngine(
        llm=FakeLLM(preset),
        benchmark=FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 98.0}),
        signals=FixtureSignalsSource(signals_events))


def test_trace_records_every_module_in_order():
    engine = _engine([{"date": "2026-05-02", "title": "patch v3.2", "kind": "patch",
                       "url": "u", "sentiment": -0.1}])
    h = engine.analyze(_profile(), _metrics(), "what happened?")
    assert h.trace is not None
    assert [ev.module for ev in h.trace.events] == ["anomaly", "segment", "market", "competitor"]
    assert [ev.step for ev in h.trace.events] == [1, 2, 3, 4]
    # the ids each module reports writing reconcile, in order, with the full ledger
    written = [i for ev in h.trace.events for i in ev.ledger_ids]
    assert written == [e.id for e in h.evidence]
    assert h.trace.total_entries == len(h.evidence)
    assert all(ev.elapsed_ms >= 0 for ev in h.trace.events)


def test_trace_flags_data_gap_module():
    engine = _engine([])  # no signals -> competitor records a derived/low gap entry
    h = engine.analyze(_profile(), _metrics(), "what happened?")
    comp = next(ev for ev in h.trace.events if ev.module == "competitor")
    assert comp.status == "data_gap" and comp.entries_added == 1
    anomaly = next(ev for ev in h.trace.events if ev.module == "anomaly")
    assert anomaly.status == "ok" and anomaly.entries_added >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trace.py -v`
Expected: FAIL — `AttributeError`/`ImportError` (`AttributionHypothesis` has no `trace`; `gaa.schema.trace` missing).

- [ ] **Step 3: Write `src/gaa/schema/trace.py`**

```python
from typing import Literal
from pydantic import BaseModel, Field

TraceStatus = Literal["ok", "data_gap", "error"]


class TraceEvent(BaseModel):
    step: int                       # 1-based execution order
    module: str                     # "anomaly" | "segment" | "market" | "competitor"
    status: TraceStatus
    entries_added: int              # ledger entries this module appended
    ledger_ids: list[str] = Field(default_factory=list)  # e.g. ["L1", "L2"]
    elapsed_ms: float = 0.0
    note: str = ""                  # error detail or gap reason


class RunTrace(BaseModel):
    query: str
    events: list[TraceEvent] = Field(default_factory=list)
    total_entries: int = 0
```

- [ ] **Step 4: Add the `trace` field to `src/gaa/schema/hypothesis.py`**

Add the import and one optional field (no other change). `trace.py` imports nothing from `hypothesis.py`, so there is no import cycle:

```python
from typing import Optional
from gaa.schema.trace import RunTrace
# ... existing imports ...


class AttributionHypothesis(BaseModel):
    main_story: str
    confidence: Confidence
    causes: Causes
    scenarios: list[Scenario] = []
    risks: list[Risk] = []
    evidence: list[LedgerEntry] = []
    assumptions_and_gaps: list[str] = []
    trace: Optional[RunTrace] = None   # NEW — populated by the engine (Task 15)
```

> Defaulting to `None` keeps every existing constructor call (synthesizer, validator, their tests) green.

- [ ] **Step 5: Populate the trace in `src/gaa/engine.py`**

Replace `analyze()` with a module loop and add the `_run_traced` helper. Behaviour is identical except that each module is timed/recorded and an unexpected exception is captured as an `error` event instead of aborting the run (modules are contractually non-raising, so this branch only fires on a real bug — better a partial, visibly-flagged result on stage than a 500):

```python
import time
from gaa.schema.trace import TraceEvent, RunTrace
# ... existing imports unchanged ...


class AttributionEngine:
    def __init__(self, llm: LLM, benchmark: BenchmarkSource, signals: SignalsSource) -> None:
        self._synth = Synthesizer(llm)
        self._benchmark = benchmark
        self._signals = signals

    def analyze(self, profile: GameProfile, metrics: pd.DataFrame,
                query: str) -> AttributionHypothesis:
        parsed = parse_query(query)
        ctx = AnalysisContext(profile=profile, metrics=metrics, query=query,
                              metric=parsed["metric"], direction=parsed["direction"])
        ledger = EvidenceLedger()
        trace = RunTrace(query=query)
        # order matters: anomaly resolves metric/window first (incl. scan mode)
        modules = [
            AnomalyDetection(),
            SegmentDecomposition(),
            MarketBenchmark(self._benchmark),
            CompetitorSignals(self._signals),
        ]
        for step, module in enumerate(modules, start=1):
            self._run_traced(module, ctx, ledger, trace, step)
        trace.total_entries = len(ledger.all())

        hyp = self._synth.synthesize(ledger, query)
        hyp = validate_citations(hyp, ledger)
        hyp.trace = trace
        return hyp

    @staticmethod
    def _run_traced(module, ctx: AnalysisContext, ledger: EvidenceLedger,
                    trace: RunTrace, step: int) -> None:
        before = len(ledger.all())
        t0 = time.perf_counter()
        status, note = "ok", ""
        try:
            module.run(ctx, ledger)
        except Exception as exc:  # modules shouldn't raise; record instead of crashing
            status, note = "error", f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        added = ledger.all()[before:]
        # a module that only logged a derived/low "data gap" entry is a gap, not a finding
        if status == "ok" and added and all(
                e.source_type == "derived" and e.strength == "low" for e in added):
            status = "data_gap"
        trace.events.append(TraceEvent(
            step=step, module=module.name, status=status,
            entries_added=len(added), ledger_ids=[e.id for e in added],
            elapsed_ms=round(elapsed_ms, 3), note=note))
```

> No `/analyze` change needed: the response already returns `hypothesis.model_dump()`, so `trace` is nested under `hypothesis` automatically. Plan 3's renderer reads `hypothesis.trace.events`; Plan 0's graph node can log/emit it.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_trace.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the full suite (no regressions)**

Run: `pytest -q`
Expected: all green — the new `trace` field defaults to `None`, so Task 1/11/12/14 tests are unaffected.

- [ ] **Step 8: Commit**

```bash
git add src/gaa/schema/trace.py src/gaa/schema/hypothesis.py src/gaa/engine.py tests/test_trace.py
git commit -m "feat: per-run reasoning trace (module status, ledger ids, timing)"
```

---

## Self-Review (completed during authoring)

**Spec coverage (Plan 2 portion):**
- Orchestrator router + planner (scan mode) → Tasks 6, 13 (router intent split finalized in Plan 3 onboarding) ✓
- 4 analysis modules → Tasks 6, 7, 8, 9 ✓
- Evidence Ledger → Task 2 ✓
- Synthesizer + citation validator → Tasks 11, 12 ✓
- Dual confidence (likelihood LLM-reasoned; evidence_quality rule-based) → Tasks 1, 3, 11 ✓
- Graceful degradation (modules log "data gap" instead of raising) → Tasks 6–9 (derived/low entries) ✓
- LLM external + MaaS fallback → Task 10 ✓
- `/analyze` returns `{html, hypothesis, markdown_summary}` → Task 14 (html stubbed for Plan 3) ✓
- Run trace / observability (per-module status, ledger ids written, data-gap/error, timing) → Task 15 ✓
- Deferred to Plan 3: live BenchmarkSource/SignalsSource (crawler), chat-assisted onboarding/router, Plotly HTML report (incl. rendering `hypothesis.trace`).

**Placeholder scan:** No TBD/TODO. The `html: ""` field is an explicit, documented Plan-3 handoff, not a placeholder gap.

**Type consistency:** `AnalysisContext(profile, metrics, query, metric, start, end, direction, extras)` used identically across modules and engine. `EvidenceLedger.add(module=, claim=, value=, source=, source_type=, strength=, timeframe=)` keyword-consistent in all 4 modules + synthesizer tests. `Confidence(likelihood, evidence_quality)`, `Cause(claim, evidence_ids, likelihood, evidence_quality)`, `Scenario(description, likelihood, evidence_quality, signals_to_watch)` consistent across Tasks 1, 11, 12, 13. `BenchmarkSource.genre_trend` / `SignalsSource.events` signatures identical in fixtures (Task 5), modules (Tasks 8, 9), and Plan 3's live sources. `evidence_quality(entries)->str` and `validate_citations(h, ledger)->h` consistent. `create_app(...)` injection params match the Plan 1 base.
