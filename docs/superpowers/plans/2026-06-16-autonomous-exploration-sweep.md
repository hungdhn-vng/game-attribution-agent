# Autonomous Exploration Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic `ExplorationSweep` analysis module that mines all metrics × dimensions for high-impact, *unprompted* findings and writes the top few into the evidence ledger so they flow into synth and the dossier like any other finding.

**Architecture:** A new module implementing the existing `AnalysisModule` protocol (`run(ctx, ledger)`, never raises). It runs **last** in `AnalysisPipeline._stage_modules` so it can read the ledger and skip what targeted modules already covered. Four probes (P1 all-metric×dim surprise scan, P2 two-way ANOVA-style interaction, P3 cross-metric lead-lag, P4 data-quality) produce ranked candidates; the top-N go to the ledger as `source_type="derived", module="exploration"`. No ledger schema change; one minimal synth-prompt touch so the LLM surfaces these.

**Tech Stack:** Python 3.11, pandas, pytest. Reuses `gaa.core.analytics.adtributor.adtributor_dimension`, `gaa.core.analytics.aggregate.{is_aggregate_label, metric_series}`, `gaa.core.schema.canonical.CANONICAL_DIMS`, `gaa.core.schema.ledger.EvidenceLedger`, `gaa.core.modules.base.AnalysisContext`.

**Spec:** `docs/superpowers/specs/2026-06-16-autonomous-exploration-sweep-design.md`

---

## File Structure

- **Create:** `src/gaa/core/modules/exploration.py` — `ExplorationSweep` module + four probe functions + small helpers. One responsibility: turn a metrics frame into ranked, ledger-ready exploration findings.
- **Create:** `tests/modules/test_exploration.py` — all unit + integration-lite tests for the module.
- **Create:** `tests/runs/test_pipeline_exploration.py` — source-inspection test that the pipeline wires the module (mirrors `tests/runs/test_pipeline_migration.py`).
- **Modify:** `src/gaa/runs/pipeline.py` — register `ExplorationSweep().run(ctx, ledger)` last in `_stage_modules`; extend the activity line.
- **Modify:** `src/gaa/core/synth/synthesizer.py` — `_ledger_brief` includes `module`; add one line to `SYSTEM`.
- **Modify:** `tests/modules/test_exploration.py` is the home for the shared test `_df`/`_ctx` builders (defined in Task 1, reused thereafter).

### Conventions to follow (from the existing code)

- Test profile: `GameProfile(name="G", platform="roblox", genre="survival", mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}))`.
- A canonical metrics frame has columns `date, metric, value` + the six `CANONICAL_DIMS = ["platform","region","version","cohort","device","source"]`; missing dims set to `None`; `df["date"] = pd.to_datetime(df["date"])`.
- `adtributor_dimension(forecast: dict, actual: dict) -> {"elements":[{"key","ep","surprise"}], "surprise", "ep_explained", "size"}`.
- `metric_series(df, metric) -> pd.Series` (one float per date, indexed & sorted by date; empty if absent).
- `ledger.add(*, module, claim, value, source, source_type, strength, timeframe=None) -> id`; `source_type ∈ {"internal","external","derived"}`; `strength ∈ {"high","med","low"}`.

---

## Task 1: Module scaffold + helpers

**Files:**
- Create: `src/gaa/core/modules/exploration.py`
- Create: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_exploration.py
import pandas as pd
import pytest
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.schema.canonical import CANONICAL_DIMS

DIMS = CANONICAL_DIMS


def _profile():
    return GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}))


def _frame(rows: list[dict]) -> pd.DataFrame:
    """rows: dicts with at least date/metric/value (+ any dims). Fills missing dims with None."""
    df = pd.DataFrame(rows)
    for c in DIMS:
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype(float)
    df["metric"] = df["metric"].astype(str)
    return df


def _ctx(df: pd.DataFrame, metric="dau", start=None, end=None, direction="down") -> AnalysisContext:
    dates = sorted(df["date"].unique())
    return AnalysisContext(profile=_profile(), metrics=df, query="why did it change",
                           metric=metric,
                           start=start or str(pd.Timestamp(dates[0]).date()),
                           end=end or str(pd.Timestamp(dates[-1]).date()),
                           direction=direction)


def test_strength_thresholds_mirror_segment():
    from gaa.core.modules.exploration import _strength
    assert _strength(0.6) == "high"
    assert _strength(-0.5) == "high"
    assert _strength(0.3) == "med"
    assert _strength(0.1) == "low"


def test_covered_pairs_parses_segment_sources():
    from gaa.core.modules.exploration import _covered_pairs
    led = EvidenceLedger()
    led.add(module="segment", claim="region=SEA explains 40% of the dau move", value="EP 40%",
            source="internal:dau by region (Adtributor)", source_type="internal", strength="high")
    led.add(module="anomaly", claim="dau changed -20% over window", value="-20%",
            source="internal:dau", source_type="internal", strength="high")
    assert ("dau", "region") in _covered_pairs(led)


def test_two_dates_picks_window_endpoints():
    from gaa.core.modules.exploration import _two_dates
    df = _frame([
        {"date": "2026-05-01", "metric": "dau", "value": 1000, "region": "SEA"},
        {"date": "2026-05-04", "metric": "dau", "value": 800, "region": "SEA"},
        {"date": "2026-05-08", "metric": "dau", "value": 400, "region": "SEA"},
    ])
    s, e = _two_dates(df[df["metric"] == "dau"], "2026-05-01", "2026-05-08")
    assert s == pd.Timestamp("2026-05-01") and e == pd.Timestamp("2026-05-08")


def test_two_dates_returns_none_for_single_date():
    from gaa.core.modules.exploration import _two_dates
    df = _frame([{"date": "2026-05-01", "metric": "dau", "value": 1000, "region": "SEA"}])
    s, e = _two_dates(df[df["metric"] == "dau"], None, None)
    assert s is None and e is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.core.modules.exploration'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/core/modules/exploration.py
"""Autonomous exploration: mine all metrics × dimensions for high-impact, *unprompted*
findings the targeted modules didn't ask about, rank them, and append the top-N to the
evidence ledger. Deterministic — the LLM only narrates. Implements AnalysisModule;
never raises (per the module contract in base.py)."""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.canonical import CANONICAL_DIMS
from gaa.core.analytics.adtributor import adtributor_dimension
from gaa.core.analytics.aggregate import is_aggregate_label, metric_series


@dataclass
class _Candidate:
    score: float
    strength: str
    claim: str
    value: str
    source: str
    timeframe: Optional[str]
    dedup_key: tuple


def _strength(effect: float) -> str:
    """Mirror segment.py: |effect|>=0.5 high, >=0.2 med, else low."""
    a = abs(effect)
    return "high" if a >= 0.5 else ("med" if a >= 0.2 else "low")


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


_SEG_SRC_RE = re.compile(r"internal:(?P<metric>[^ ]+) by (?P<dim>\w+) \(Adtributor\)")


def _covered_pairs(ledger: EvidenceLedger) -> set[tuple[str, str]]:
    """(metric, dim) pairs already decomposed by the segment module, parsed from its
    source strings (e.g. 'internal:dau by region (Adtributor)')."""
    pairs: set[tuple[str, str]] = set()
    for e in ledger.all():
        if e.module == "segment":
            m = _SEG_SRC_RE.search(e.source)
            if m:
                pairs.add((m.group("metric"), m.group("dim")))
    return pairs


def _two_dates(df_metric: pd.DataFrame, start, end):
    """Comparison endpoints for a metric subframe: prefer ctx start/end when present in
    the data, else the metric's own first/last date. Returns (None, None) if <2 dates."""
    dates = sorted(pd.Timestamp(d) for d in df_metric["date"].unique())
    if len(dates) < 2:
        return None, None
    s = pd.Timestamp(start) if start else dates[0]
    e = pd.Timestamp(end) if end else dates[-1]
    if s not in dates:
        s = dates[0]
    if e not in dates:
        e = dates[-1]
    return s, e


def _safe(fn, *args) -> list[_Candidate]:
    """Run a probe; never let it raise (module contract). Returns [] on failure."""
    try:
        return fn(*args)
    except Exception:
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/modules/test_exploration.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/exploration.py tests/modules/test_exploration.py
git commit -m "feat(exploration): module scaffold + helpers (strength/covered-pairs/two-dates)"
```

---

## Task 2: P1 — all-metric × all-dimension surprise scan

**Files:**
- Modify: `src/gaa/core/modules/exploration.py`
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/modules/test_exploration.py

def test_p1_finds_mover_in_unqueried_metric():
    from gaa.core.modules.exploration import _p1_surprise_scan
    # queried metric is dau; the *interesting* unprompted move is revenue collapsing in SEA
    rows = []
    for d, (dau_sea, dau_na, rev_sea, rev_na) in {
        "2026-05-01": (1000, 1000, 1000, 1000),
        "2026-05-08": (950, 1000, 100, 1000),
    }.items():
        rows += [
            {"date": d, "metric": "dau", "value": dau_sea, "region": "SEA"},
            {"date": d, "metric": "dau", "value": dau_na, "region": "NA"},
            {"date": d, "metric": "revenue", "value": rev_sea, "region": "SEA"},
            {"date": d, "metric": "revenue", "value": rev_na, "region": "NA"},
        ]
    ctx = _ctx(_frame(rows), metric="dau", start="2026-05-01", end="2026-05-08")
    cands = _p1_surprise_scan(ctx, covered=set())
    joined = " | ".join(c.claim for c in cands)
    assert "revenue" in joined and "SEA" in joined


def test_p1_skips_pairs_already_covered():
    from gaa.core.modules.exploration import _p1_surprise_scan
    rows = []
    for d, (sea, na) in {"2026-05-01": (1000, 1000), "2026-05-08": (400, 1000)}.items():
        rows += [{"date": d, "metric": "dau", "value": sea, "region": "SEA"},
                 {"date": d, "metric": "dau", "value": na, "region": "NA"}]
    ctx = _ctx(_frame(rows), metric="dau", start="2026-05-01", end="2026-05-08")
    cands = _p1_surprise_scan(ctx, covered={("dau", "region")})
    assert all("by region" not in c.source for c in cands)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -k p1 -q`
Expected: FAIL — `cannot import name '_p1_surprise_scan'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/gaa/core/modules/exploration.py`:

```python
def _p1_surprise_scan(ctx: AnalysisContext, covered: set[tuple[str, str]]) -> list[_Candidate]:
    """For every metric × dimension NOT already covered by a targeted module, run
    Adtributor between the window endpoints and emit its surprising elements."""
    out: list[_Candidate] = []
    for metric in ctx.metrics["metric"].unique():
        dfm = ctx.metrics[ctx.metrics["metric"] == metric]
        s, e = _two_dates(dfm, ctx.start, ctx.end)
        if s is None:
            continue
        for dim in CANONICAL_DIMS:
            if (metric, dim) in covered:
                continue
            if dim not in dfm.columns or dfm[dim].isna().all():
                continue
            sub = dfm[~is_aggregate_label(dfm[dim])]
            forecast = sub[sub["date"] == s].groupby(dim)["value"].sum().to_dict()
            actual = sub[sub["date"] == e].groupby(dim)["value"].sum().to_dict()
            if not forecast or not actual:
                continue
            res = adtributor_dimension(forecast, actual)
            for el in res["elements"]:
                ep, sur = el["ep"], el["surprise"]
                if abs(ep) < 0.1:
                    continue
                out.append(_Candidate(
                    score=abs(ep) * (1.0 + sur),
                    strength=_strength(ep),
                    claim=f"{dim}={el['key']} drove {ep * 100:.0f}% of the {metric} move (unprompted)",
                    value=f"EP {ep * 100:.0f}% · surprise {sur:.3f}",
                    source=f"internal:{metric} by {dim} (exploration/Adtributor)",
                    timeframe=f"{s.date()}..{e.date()}",
                    dedup_key=(metric, dim, str(el["key"])),
                ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/modules/test_exploration.py -k p1 -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/exploration.py tests/modules/test_exploration.py
git commit -m "feat(exploration): P1 all-metric x dim surprise scan with novelty gate"
```

---

## Task 3: P2 — two-way interaction scan (ANOVA-style residual)

**Files:**
- Modify: `src/gaa/core/modules/exploration.py`
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/modules/test_exploration.py

def test_p2_finds_two_way_interaction():
    from gaa.core.modules.exploration import _p2_interaction
    # All four cells equal at start; at end ONLY region=SEA × version=v2.3 collapses.
    # Neither region nor version alone fully explains it -> interaction residual is the signal.
    rows = []
    cells = [("SEA", "v2.3"), ("SEA", "v2.2"), ("NA", "v2.3"), ("NA", "v2.2")]
    for d in ("2026-05-01",):
        for reg, ver in cells:
            rows.append({"date": d, "metric": "dau", "value": 1000, "region": reg, "version": ver})
    for d in ("2026-05-08",):
        for reg, ver in cells:
            val = 200 if (reg, ver) == ("SEA", "v2.3") else 1000
            rows.append({"date": d, "metric": "dau", "value": val, "region": reg, "version": ver})
    ctx = _ctx(_frame(rows), metric="dau", start="2026-05-01", end="2026-05-08")
    cands = _p2_interaction(ctx)
    assert cands, "expected an interaction candidate"
    top = cands[0].claim
    assert "SEA" in top and "v2.3" in top and "interaction" in cands[0].source


def test_p2_no_metric_returns_empty():
    from gaa.core.modules.exploration import _p2_interaction
    rows = [{"date": "2026-05-01", "metric": "dau", "value": 1000, "region": "SEA"},
            {"date": "2026-05-08", "metric": "dau", "value": 400, "region": "SEA"}]
    ctx = _ctx(_frame(rows), metric=None)
    assert _p2_interaction(ctx) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -k p2 -q`
Expected: FAIL — `cannot import name '_p2_interaction'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/gaa/core/modules/exploration.py`:

```python
def _marg_surprise(dfm: pd.DataFrame, dim: str, s, e) -> float:
    sub = dfm[~is_aggregate_label(dfm[dim])]
    f = sub[sub["date"] == s].groupby(dim)["value"].sum().to_dict()
    a = sub[sub["date"] == e].groupby(dim)["value"].sum().to_dict()
    return adtributor_dimension(f, a)["surprise"] if f and a else 0.0


def _p2_interaction(ctx: AnalysisContext) -> list[_Candidate]:
    """Find the dimension-pair CELL whose delta is not explained by additive main effects
    (two-way ANOVA-style interaction residual on the start->end delta matrix)."""
    metric = ctx.metric
    if not metric:
        return []
    dfm = ctx.metrics[ctx.metrics["metric"] == metric]
    s, e = _two_dates(dfm, ctx.start, ctx.end)
    if s is None:
        return []
    dims = [d for d in CANONICAL_DIMS
            if d in dfm.columns and not dfm[d].isna().all() and dfm[d].nunique() >= 2]
    dims = sorted(dims, key=lambda d: _marg_surprise(dfm, d, s, e), reverse=True)[:3]
    out: list[_Candidate] = []
    for da, db in itertools.combinations(dims, 2):
        sub = dfm[~is_aggregate_label(dfm[da]) & ~is_aggregate_label(dfm[db])]
        f = sub[sub["date"] == s].groupby([da, db])["value"].sum()
        a = sub[sub["date"] == e].groupby([da, db])["value"].sum()
        cells = a.index.union(f.index)
        delta = {c: float(a.get(c, 0.0)) - float(f.get(c, 0.0)) for c in cells}
        if len(delta) < 2:
            continue
        keys_a = sorted({c[0] for c in delta})
        keys_b = sorted({c[1] for c in delta})
        grand = _mean(list(delta.values()))
        row_mean = {ka: _mean([delta.get((ka, kb), 0.0) for kb in keys_b]) for ka in keys_a}
        col_mean = {kb: _mean([delta.get((ka, kb), 0.0) for ka in keys_a]) for kb in keys_b}
        total = sum(delta.values())
        denom = abs(total) if abs(total) > 1e-9 else 1e-9
        best = None
        for (ka, kb), d in delta.items():
            resid = d - (row_mean[ka] + col_mean[kb] - grand)
            score = abs(resid) / denom
            if best is None or score > best[0]:
                best = (score, ka, kb, d, resid)
        if best and best[0] >= 0.2:
            score, ka, kb, d, resid = best
            out.append(_Candidate(
                score=score,
                strength=_strength(score),
                claim=(f"{metric} move concentrates in {da}={ka} × {db}={kb} "
                       f"beyond what {da} or {db} explain alone"),
                value=f"cell Δ {d:+.0f} · interaction residual {resid:+.0f}",
                source=f"internal:{metric} by {da}×{db} (exploration/interaction)",
                timeframe=f"{s.date()}..{e.date()}",
                dedup_key=(metric, f"{da}×{db}", f"{ka}×{kb}"),
            ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/modules/test_exploration.py -k p2 -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/exploration.py tests/modules/test_exploration.py
git commit -m "feat(exploration): P2 two-way ANOVA-style interaction scan"
```

---

## Task 4: P3 — cross-metric lead-lag

**Files:**
- Modify: `src/gaa/core/modules/exploration.py`
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/modules/test_exploration.py

def test_p3_detects_leading_indicator():
    from gaa.core.modules.exploration import _p3_lead_lag
    # retention_d7 leads dau by 3 days: dau(t) tracks retention_d7(t-3).
    import numpy as np
    dates = pd.date_range("2026-05-01", periods=14, freq="D")
    base = np.linspace(1000, 500, 14)            # a clear decline
    ret = base.copy()
    dau = np.empty(14)
    dau[:3] = 1000
    dau[3:] = base[:11]                          # dau lags retention by 3 days
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": str(d.date()), "metric": "retention_d7", "value": float(ret[i])})
        rows.append({"date": str(d.date()), "metric": "dau", "value": float(dau[i])})
    ctx = _ctx(_frame(rows), metric="dau")
    cands = _p3_lead_lag(ctx)
    assert cands, "expected a lead-lag candidate"
    assert "retention_d7" in cands[0].claim and "before" in cands[0].claim


def test_p3_requires_target_present():
    from gaa.core.modules.exploration import _p3_lead_lag
    rows = [{"date": f"2026-05-0{i+1}", "metric": "dau", "value": 1000 - 50 * i} for i in range(6)]
    ctx = _ctx(_frame(rows), metric="revenue")   # not in data
    assert _p3_lead_lag(ctx) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -k p3 -q`
Expected: FAIL — `cannot import name '_p3_lead_lag'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/gaa/core/modules/exploration.py`:

```python
def _p3_lead_lag(ctx: AnalysisContext) -> list[_Candidate]:
    """Find other metrics whose series LEADS the target metric (positive lag, strong
    correlation) — a candidate leading indicator. lag>0 means `other` moves first."""
    target = ctx.metric
    metrics = list(ctx.metrics["metric"].unique())
    series = {m: metric_series(ctx.metrics, m) for m in metrics}
    series = {m: s for m, s in series.items() if len(s) >= 5}
    if target not in series:
        return []
    tgt = series[target]
    out: list[_Candidate] = []
    for m, s in series.items():
        if m == target:
            continue
        best = (0.0, 0)  # (corr, lag)
        for lag in range(1, 8):                  # only positive lags: does `m` lead `tgt`?
            shifted = s.shift(lag)               # shifted[t] = m[t-lag]; correlate with tgt[t]
            joined = pd.concat([tgt, shifted], axis=1, join="inner").dropna()
            if len(joined) < 4:
                continue
            c = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            if c is not None and abs(c) > abs(best[0]):
                best = (float(c), lag)
        corr, lag = best
        if abs(corr) >= 0.7 and lag > 0:
            out.append(_Candidate(
                score=abs(corr) * (1.0 + lag / 7.0),
                strength=_strength(abs(corr)),
                claim=(f"{m} moves ~{lag}d before {target} (corr {corr:+.2f}) — "
                       f"possible leading indicator"),
                value=f"corr {corr:+.2f} at lag {lag}d",
                source=f"internal:{m}→{target} (exploration/lead-lag)",
                timeframe=None,
                dedup_key=(m, "lead-lag", target),
            ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out
```

Note: if `test_p3_detects_leading_indicator` finds `lag` off by a fixed amount or the
sign inverted, the planted signal in the test is the ground truth — adjust the `shift`
direction/range here until the planted 3-day lead is detected, not the test.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/modules/test_exploration.py -k p3 -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/exploration.py tests/modules/test_exploration.py
git commit -m "feat(exploration): P3 cross-metric lead-lag (leading-indicator) probe"
```

---

## Task 5: P4 — data-quality flags

**Files:**
- Modify: `src/gaa/core/modules/exploration.py`
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/modules/test_exploration.py

def test_p4_flags_nonpositive_and_jump():
    from gaa.core.modules.exploration import _p4_data_quality
    rows = [
        {"date": "2026-05-01", "metric": "dau", "value": 1000},
        {"date": "2026-05-02", "metric": "dau", "value": 0},        # non-positive
        {"date": "2026-05-03", "metric": "dau", "value": 9000},     # ~huge jump
        {"date": "2026-05-04", "metric": "dau", "value": 9100},
    ]
    cands = _p4_data_quality(_ctx(_frame(rows), metric="dau"))
    assert cands, "expected at least one data-quality flag"
    assert all(c.strength == "low" for c in cands)
    blob = " ".join(c.claim for c in cands)
    assert "data" in blob.lower()


def test_p4_clean_series_no_flags():
    from gaa.core.modules.exploration import _p4_data_quality
    rows = [{"date": f"2026-05-0{i+1}", "metric": "dau", "value": 1000 - 20 * i} for i in range(6)]
    assert _p4_data_quality(_ctx(_frame(rows), metric="dau")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -k p4 -q`
Expected: FAIL — `cannot import name '_p4_data_quality'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/gaa/core/modules/exploration.py`:

```python
def _p4_data_quality(ctx: AnalysisContext) -> list[_Candidate]:
    """Cheap reliability caveats: non-positive values and abrupt single-step jumps.
    Always low-strength; these also feed synth's assumptions_and_gaps."""
    out: list[_Candidate] = []
    for m in ctx.metrics["metric"].unique():
        s = metric_series(ctx.metrics, m)
        if s.empty:
            continue
        n_nonpos = int((s <= 0).sum())
        if n_nonpos:
            out.append(_Candidate(
                score=0.05, strength="low",
                claim=f"{m} has {n_nonpos} non-positive value(s) — possible data gap/outlier",
                value=f"{n_nonpos} non-positive points",
                source=f"internal:{m} (exploration/data-quality)",
                timeframe=None, dedup_key=(m, "dq", "nonpos")))
        pct = s.pct_change().abs().replace([float("inf")], pd.NA).dropna()
        if len(pct) and pct.max() >= 5.0:        # >=500% single-step jump
            out.append(_Candidate(
                score=0.05, strength="low",
                claim=f"{m} has an abrupt {pct.max() * 100:.0f}% single-step jump — verify data integrity",
                value=f"max step {pct.max() * 100:.0f}%",
                source=f"internal:{m} (exploration/data-quality)",
                timeframe=None, dedup_key=(m, "dq", "jump")))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/modules/test_exploration.py -k p4 -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/exploration.py tests/modules/test_exploration.py
git commit -m "feat(exploration): P4 data-quality flag probe"
```

---

## Task 6: `ExplorationSweep` — rank, dedup, cap, never-raise

**Files:**
- Modify: `src/gaa/core/modules/exploration.py`
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/modules/test_exploration.py

def _rich_frame():
    # dau queried; revenue collapses in SEA (P1); SEA×v2.3 interaction (P2).
    rows = []
    cells = [("SEA", "v2.3"), ("SEA", "v2.2"), ("NA", "v2.3"), ("NA", "v2.2")]
    for d, factor in (("2026-05-01", 1.0), ("2026-05-08", None)):
        for reg, ver in cells:
            dau = 1000 if factor else (200 if (reg, ver) == ("SEA", "v2.3") else 1000)
            rev = 1000 if factor else (100 if reg == "SEA" else 1000)
            rows.append({"date": d, "metric": "dau", "value": dau, "region": reg, "version": ver})
            rows.append({"date": d, "metric": "revenue", "value": rev, "region": reg, "version": ver})
    return _frame(rows)


def test_run_appends_exploration_findings_to_ledger():
    from gaa.core.modules.exploration import ExplorationSweep
    led = EvidenceLedger()
    ExplorationSweep().run(_ctx(_rich_frame(), metric="dau", start="2026-05-01", end="2026-05-08"), led)
    explored = [e for e in led.all() if e.module == "exploration"]
    assert explored, "exploration must write at least one finding"
    assert all(e.source_type == "derived" for e in explored)


def test_run_caps_at_top_n():
    from gaa.core.modules.exploration import ExplorationSweep
    led = EvidenceLedger()
    ExplorationSweep(top_n=1).run(
        _ctx(_rich_frame(), metric="dau", start="2026-05-01", end="2026-05-08"), led)
    ranked = [e for e in led.all()
              if e.module == "exploration" and "data-quality" not in e.source]
    assert len(ranked) == 1                       # P4 caveats are exempt from the cap


def test_run_respects_novelty_from_segment():
    from gaa.core.modules.exploration import ExplorationSweep
    led = EvidenceLedger()
    # pretend segment already decomposed dau by region
    led.add(module="segment", claim="region=SEA explains 80% of the dau move", value="EP 80%",
            source="internal:dau by region (Adtributor)", source_type="internal", strength="high")
    ExplorationSweep().run(_ctx(_rich_frame(), metric="dau", start="2026-05-01", end="2026-05-08"), led)
    explored = [e for e in led.all() if e.module == "exploration"]
    assert all("dau by region" not in e.source for e in explored)


def test_run_never_raises_on_empty_frame():
    from gaa.core.modules.exploration import ExplorationSweep
    from gaa.core.schema.canonical import empty_canonical
    led = EvidenceLedger()
    ctx = AnalysisContext(profile=_profile(), metrics=empty_canonical(), query="q",
                          metric="dau", start=None, end=None, direction=None)
    ExplorationSweep().run(ctx, led)              # must not raise
    assert True


def test_run_disabled_writes_nothing():
    from gaa.core.modules.exploration import ExplorationSweep
    led = EvidenceLedger()
    ExplorationSweep(enabled=False).run(
        _ctx(_rich_frame(), metric="dau", start="2026-05-01", end="2026-05-08"), led)
    assert [e for e in led.all() if e.module == "exploration"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -k run -q`
Expected: FAIL — `cannot import name 'ExplorationSweep'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/gaa/core/modules/exploration.py`:

```python
class ExplorationSweep:
    """Runs the probe battery, ranks candidates, applies the novelty gate + top-N cap,
    and appends findings to the ledger. P4 data-quality caveats are exempt from the cap."""
    name = "exploration"

    def __init__(self, top_n: int = 4, enabled: bool = True) -> None:
        self._top_n = top_n
        self._enabled = enabled

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not self._enabled:
            return
        try:
            covered = _covered_pairs(ledger)
            cands = (_safe(_p1_surprise_scan, ctx, covered)
                     + _safe(_p2_interaction, ctx)
                     + _safe(_p3_lead_lag, ctx))
            seen: set[tuple] = set()
            ranked: list[_Candidate] = []
            for c in sorted(cands, key=lambda c: c.score, reverse=True):
                if c.dedup_key in seen:
                    continue
                seen.add(c.dedup_key)
                ranked.append(c)
            kept = ranked[:self._top_n]
            dropped = len(ranked) - len(kept)
            for c in kept:
                ledger.add(module=self.name, claim=c.claim, value=c.value, source=c.source,
                           source_type="derived", strength=c.strength, timeframe=c.timeframe)
            for c in _safe(_p4_data_quality, ctx):   # caveats: always appended, exempt from cap
                ledger.add(module=self.name, claim=c.claim, value=c.value, source=c.source,
                           source_type="derived", strength=c.strength, timeframe=c.timeframe)
            ctx.extras["exploration_dropped"] = dropped
            ctx.extras["exploration_kept"] = len(kept)
        except Exception:
            ledger.add(module=self.name, claim="exploration sweep encountered an error",
                       value="n/a", source="internal", source_type="derived", strength="low")
```

- [ ] **Step 4: Run the full module test file**

Run: `python -m pytest tests/modules/test_exploration.py -q`
Expected: PASS (all tests across Tasks 1–6).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/exploration.py tests/modules/test_exploration.py
git commit -m "feat(exploration): ExplorationSweep run — rank/dedup/cap/never-raise"
```

---

## Task 7: Wire into the pipeline

**Files:**
- Modify: `src/gaa/runs/pipeline.py` (imports near top with the other module imports; `_stage_modules` ~line 220-229)
- Create: `tests/runs/test_pipeline_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runs/test_pipeline_exploration.py
import inspect
from gaa.runs import pipeline


def test_pipeline_runs_exploration_sweep_last():
    src = inspect.getsource(pipeline.AnalysisPipeline._stage_modules)
    assert "ExplorationSweep" in src, "modules stage must run ExplorationSweep"
    # must run AFTER the targeted modules so the novelty gate can see their findings
    assert src.index("ExplorationSweep") > src.index("MigrationPattern")
    assert "from gaa.core.modules.exploration import ExplorationSweep" in inspect.getsource(pipeline)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/runs/test_pipeline_exploration.py -q`
Expected: FAIL — `AssertionError` (ExplorationSweep not in source).

- [ ] **Step 3: Add the import and the call**

In `src/gaa/runs/pipeline.py`, add the import alongside the existing module imports (near `from gaa.core.modules.migration import MigrationPattern`):

```python
from gaa.core.modules.exploration import ExplorationSweep
```

In `_stage_modules`, after the `MigrationPattern().run(ctx, ledger)` line, add the sweep and update the activity line:

```python
        MigrationPattern().run(ctx, ledger)
        ExplorationSweep().run(ctx, ledger)        # runs last: mines unprompted findings

        state["ledger"] = [e.model_dump() for e in ledger.all()]
        explored = sum(1 for e in ledger.all() if e.module == "exploration")
        job.add_activity(
            "modules",
            f"Segment/Market/Competitor analyzed; {explored} exploration finding(s); "
            f"ledger has {len(ledger.all())} entries",
        )
        job.stage = "synth"
```

(Replace the existing `state["ledger"] = ...` / `job.add_activity(...)` / `job.stage = "synth"`
block in `_stage_modules` with the version above — do not duplicate it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/runs/test_pipeline_exploration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/runs/pipeline.py tests/runs/test_pipeline_exploration.py
git commit -m "feat(exploration): wire ExplorationSweep last into pipeline _stage_modules"
```

---

## Task 8: Synth awareness (minimal)

**Files:**
- Modify: `src/gaa/core/synth/synthesizer.py` (`_ledger_brief` ~line 23-26; `SYSTEM` ~line 10-20)
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/modules/test_exploration.py

def test_ledger_brief_includes_module_tag():
    from gaa.core.synth.synthesizer import _ledger_brief
    led = EvidenceLedger()
    led.add(module="exploration", claim="revenue collapsed in SEA", value="EP -60%",
            source="internal:revenue by region (exploration/Adtributor)",
            source_type="derived", strength="high")
    brief = _ledger_brief(led)
    assert "exploration" in brief and "revenue collapsed in SEA" in brief


def test_system_prompt_mentions_exploration():
    from gaa.core.synth import synthesizer
    assert "exploration" in synthesizer.SYSTEM.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/modules/test_exploration.py -k "ledger_brief or system_prompt" -q`
Expected: FAIL — `_ledger_brief` output lacks `exploration` / `SYSTEM` lacks the word.

- [ ] **Step 3: Edit the synthesizer**

In `src/gaa/core/synth/synthesizer.py`, change `_ledger_brief` to include the module:

```python
def _ledger_brief(ledger: EvidenceLedger) -> str:
    return "\n".join(
        f"{e.id} [{e.source_type}/{e.strength}/{e.module}] {e.claim} ({e.value}) src={e.source}"
        for e in ledger.all())
```

Add one sentence to the end of the `SYSTEM` string (before the closing `)`):

```python
    "assumptions_and_gaps is an array of plain strings (one short sentence each), NOT objects. "
    "Evidence whose module is 'exploration' are proactive findings the user did not explicitly "
    "ask about — surface the notable ones in main_story or scenarios when they matter."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/modules/test_exploration.py -k "ledger_brief or system_prompt" -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/synth/synthesizer.py tests/modules/test_exploration.py
git commit -m "feat(exploration): synth surfaces module tag + exploration findings"
```

---

## Task 9: Robustness sweep + full suite green

**Files:**
- Modify: `tests/modules/test_exploration.py`

- [ ] **Step 1: Write the failing/edge tests**

```python
# append to tests/modules/test_exploration.py

def test_run_handles_missing_all_dims():
    from gaa.core.modules.exploration import ExplorationSweep
    rows = [{"date": f"2026-05-0{i+1}", "metric": "dau", "value": 1000 - 30 * i} for i in range(6)]
    led = EvidenceLedger()
    ExplorationSweep().run(_ctx(_frame(rows), metric="dau"), led)   # no dim columns populated
    assert True  # must not raise


def test_run_handles_single_date():
    from gaa.core.modules.exploration import ExplorationSweep
    rows = [{"date": "2026-05-01", "metric": "dau", "value": 1000, "region": "SEA"},
            {"date": "2026-05-01", "metric": "dau", "value": 800, "region": "NA"}]
    led = EvidenceLedger()
    ExplorationSweep().run(_ctx(_frame(rows), metric="dau"), led)   # only one date
    assert True


def test_run_handles_all_nan_dimension():
    from gaa.core.modules.exploration import ExplorationSweep
    rows = []
    for d, v in (("2026-05-01", 1000), ("2026-05-08", 400)):
        rows.append({"date": d, "metric": "dau", "value": v})       # region etc. all None
    led = EvidenceLedger()
    ExplorationSweep().run(_ctx(_frame(rows), metric="dau", start="2026-05-01", end="2026-05-08"), led)
    assert True
```

- [ ] **Step 2: Run the edge tests**

Run: `python -m pytest tests/modules/test_exploration.py -k "missing_all_dims or single_date or all_nan" -q`
Expected: PASS (3 passed). If any raises, the offending probe needs a guard — wrap the failing computation so it skips gracefully (the `_safe` wrapper in `run` already contains probe-level failures; only fix a probe if a test still fails).

- [ ] **Step 3: Run the entire test suite**

Run: `python -m pytest -q`
Expected: PASS — all pre-existing tests plus the new exploration tests green. (Baseline before this work was ~360 passing.)

- [ ] **Step 4: Commit**

```bash
git add tests/modules/test_exploration.py
git commit -m "test(exploration): robustness edge cases (no dims/single date/all-NaN)"
```

---

## Self-Review (completed during authoring)

**Spec coverage:**
- §Probe battery P1 → Task 2; P2 → Task 3; P3 → Task 4; P4 → Task 5. ✓
- §Architecture & integration (new module, runs last, derived/module tag) → Task 1 + Task 6 + Task 7. ✓
- §Scoring/novelty/cap → Task 6 (`run`) + Task 2 (`_covered_pairs` gate). ✓
- §Synth awareness (minimal) → Task 8. ✓
- §Config (enable/top_n) → realized as **constructor params** `ExplorationSweep(top_n=4, enabled=True)` (Task 6). *Deviation from spec:* config-KEY wiring through `config.py`/`config_get/set` is **deferred** — constructor params satisfy "configurable" for v1 without adding runtime-config surface; flagged here per the spec's "Open" note. ✓ (documented)
- §Error handling (never-raise) → Task 6 (`run` try/except + `_safe`) and Task 9 (edge tests). ✓
- §Testing strategy → Tasks 2–9 (planted-signal, novelty, cap, robustness, integration-lite, pipeline-wiring). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The P3 note tells the engineer to treat the planted-signal test as ground truth for the `shift` sign — that is guidance, not a placeholder (full code is present).

**Type consistency:** `_Candidate` fields (score/strength/claim/value/source/timeframe/dedup_key) are used identically in P1–P4 and in `ExplorationSweep.run`. `_covered_pairs`, `_two_dates`, `_strength`, `_mean`, `_safe` signatures match every call site. `ledger.add(...)` keyword args match the real schema. Probe function names (`_p1_surprise_scan`, `_p2_interaction`, `_p3_lead_lag`, `_p4_data_quality`) are consistent between definition, tests, and `run`.

**Risk flagged for execution:** P2/P3 score magnitudes are heuristic; tests assert the *right finding ranks/appears*, not exact scores — keep it that way (don't tighten tests to brittle numeric thresholds).
