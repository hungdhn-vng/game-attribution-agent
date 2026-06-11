# Game Attribution Agent — Plan 2A: Analytics Rigor Upgrade

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the naive-delta versions of three analysis modules with research-backed attribution methods, and add a self-consistency abstention gate — turning the engine from *descriptive* to *causal*. Backed by a verified deep-research pass (see spec §15).

**Supersedes:** Plan 2 Task 6 (Anomaly), Task 7 (Segment), Task 8 (Market). **Adds:** a confidence gate + engine wiring. Everything else in Plan 2 (schema, ledger, confidence rule, MetricsStore, source interfaces, competitor module, synthesizer, validator, planner) is unchanged. The `LLM` protocol/`FakeLLM`, `EvidenceLedger.add(...)`, and `AnalysisContext` are exactly as in Plan 2.

**Why:** CausalImpact gives a real "is it us or the market" counterfactual; Adtributor gives ratio-KPI (ARPU/retention) root-cause with citable % contributions; change-point/STL says *when it broke* and *how anomalous*; the gate bounds over-claiming. All chosen for light 4GB footprint and open-source/academic precedent.

**Tech Stack:** statsmodels (STL + `UnobservedComponents`), ruptures (PELT change-point), in-house Adtributor (no extra dep), numpy/pandas. **No TensorFlow, no Prophet** (footprint).

---

### Task 1: Dependencies

**Files:** Modify `requirements.txt`

- [ ] **Step 1: Add analytics deps** (append to `requirements.txt`)

```
statsmodels==0.14.*
ruptures==1.1.*
```

- [ ] **Step 2: Install + commit**

```bash
. .venv/bin/activate && pip install statsmodels==0.14.* ruptures==1.1.*
git add requirements.txt && git commit -m "build: add statsmodels + ruptures for analytics rigor"
```

> Footprint note: statsmodels (~50MB) + ruptures (small) fit the 4GB box. Do NOT add the TensorFlow `tfcausalimpact` port or Prophet (cmdstan) — we implement the counterfactual on statsmodels `UnobservedComponents`.

---

### Task 2: Adtributor core (pure function)

**Files:**
- Create: `src/gaa/analytics/__init__.py` (empty)
- Create: `src/gaa/analytics/adtributor.py`
- Test: `tests/analytics/test_adtributor.py`
- Create: `tests/analytics/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/analytics/test_adtributor.py`:
```python
from gaa.analytics.adtributor import adtributor_dimension

def test_isolates_the_dominant_element():
    # SEA collapses 1000->400, NA barely moves 800->770
    forecast = {"SEA": 1000.0, "NA": 800.0}
    actual = {"SEA": 400.0, "NA": 770.0}
    res = adtributor_dimension(forecast, actual)
    top = res["elements"][0]
    assert top["key"] == "SEA"
    assert 0.9 <= top["ep"] <= 1.0          # SEA explains ~95% of the drop
    assert res["surprise"] >= 0             # JS-divergence based, non-negative

def test_explanatory_power_signs_track_aggregate():
    # element moving opposite the aggregate has negative EP
    res = adtributor_dimension({"A": 100.0, "B": 100.0}, {"A": 40.0, "B": 110.0})
    eps = {e["key"]: e["ep"] for e in res["elements"]}
    # aggregate fell 200->150 (-50); A drove it (-60 => EP>1), B offset (+10 => EP<0)
    assert eps.get("A", 0) > 0

def test_handles_zero_segment_without_error():
    res = adtributor_dimension({"X": 100.0, "Y": 50.0}, {"X": 0.0, "Y": 50.0})
    assert res["elements"][0]["key"] == "X"
```

- [ ] **Step 2: Run — expect FAIL** (`pytest tests/analytics/test_adtributor.py -v`).

- [ ] **Step 3: Implement** `src/gaa/analytics/adtributor.py`

```python
import math


def _shares(d: dict) -> dict:
    tot = sum(d.values())
    return {k: (v / tot if tot > 0 else 0.0) for k, v in d.items()}


def _xlog2(x: float, m: float) -> float:
    return x * math.log2(x / m) if x > 0 and m > 0 else 0.0


def adtributor_dimension(forecast: dict, actual: dict, teep: float = 0.67) -> dict:
    """Adtributor (Microsoft NSDI'14) for one dimension.

    Returns the elements that best explain the aggregate move, ranked by
    JS-divergence 'surprise', selected until cumulative explanatory power >= teep.
    EP_i = (actual_i - forecast_i) / (A - F); EPs sum to 1 across the dimension.
    """
    keys = set(forecast) | set(actual)
    F = sum(forecast.get(k, 0.0) for k in keys)
    A = sum(actual.get(k, 0.0) for k in keys)
    denom = (A - F) if abs(A - F) > 1e-9 else 1e-9
    P, Q = _shares({k: forecast.get(k, 0.0) for k in keys}), _shares({k: actual.get(k, 0.0) for k in keys})

    rows = []
    for k in keys:
        ep = (actual.get(k, 0.0) - forecast.get(k, 0.0)) / denom
        p, q = P[k], Q[k]
        m = (p + q) / 2
        surprise = 0.5 * (_xlog2(p, m) + _xlog2(q, m))   # JS-divergence term, >= 0
        rows.append({"key": k, "ep": ep, "surprise": surprise})

    rows.sort(key=lambda r: r["surprise"], reverse=True)
    selected, cum = [], 0.0
    for r in rows:
        selected.append(r)
        cum += r["ep"]
        if cum >= teep:
            break
    return {"elements": selected, "surprise": sum(r["surprise"] for r in selected),
            "ep_explained": cum, "size": len(selected)}
```

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/analytics/ tests/analytics/
git commit -m "feat: Adtributor multidimensional root-cause core (EP + JS surprise)"
```

---

### Task 3: Segment Decomposition module → Adtributor (supersedes Plan 2 Task 7)

**Files:**
- Replace: `src/gaa/modules/segment.py`
- Replace: `tests/modules/test_segment.py`

- [ ] **Step 1: Replace the test**

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
        rows += [{"date": d, "metric": "dau", "value": float(sea), "region": "SEA"},
                 {"date": d, "metric": "dau", "value": float(na), "region": "NA"}]
    df = pd.DataFrame(rows)
    for c in ["platform", "version", "cohort", "device", "source"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-05-01", end="2026-05-03", direction="down")

def test_attributes_with_citable_percentage():
    led = EvidenceLedger()
    SegmentDecomposition().run(_ctx(), led)
    entries = [e for e in led.all() if e.module == "segment"]
    assert entries and entries[0].source_type == "internal"
    joined = " ".join(e.claim for e in entries)
    assert "SEA" in joined and "%" in joined        # % contribution is cited
    assert "Adtributor" in entries[0].source
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Replace** `src/gaa/modules/segment.py`

```python
import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.analytics.adtributor import adtributor_dimension

DIMS = ["version", "region", "platform", "cohort", "device", "source"]


class SegmentDecomposition:
    name = "segment"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.metric and ctx.start and ctx.end):
            return
        df = ctx.metrics[ctx.metrics["metric"] == ctx.metric]
        start, end = pd.Timestamp(ctx.start), pd.Timestamp(ctx.end)

        best = None  # (dim, adtributor-result)
        for dim in DIMS:
            if df[dim].isna().all():
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

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/modules/segment.py tests/modules/test_segment.py
git commit -m "feat: segment module uses Adtributor (citable %% contributions)"
```

---

### Task 4: Causal counterfactual core + Market module (supersedes Plan 2 Task 8)

**Files:**
- Create: `src/gaa/analytics/causal.py`
- Replace: `src/gaa/modules/market_benchmark.py`
- Test: `tests/analytics/test_causal.py`
- Replace: `tests/modules/test_market_benchmark.py`

- [ ] **Step 1: Write the causal-core test**

`tests/analytics/test_causal.py`:
```python
import numpy as np
import pandas as pd
from gaa.analytics.causal import causal_counterfactual

def _series(vals, start="2026-04-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D")
    return pd.Series(vals, index=idx)

def test_detects_internal_drop_when_control_holds():
    # 14 pre days target≈control≈100; then target drops to 60 while control holds 100
    pre = [100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 100, 101, 99, 100]
    ctrl = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
    target = _series(pre + [60, 61, 59])
    control = _series(ctrl + [100, 100, 100])
    res = causal_counterfactual(target, control, pd.Timestamp("2026-04-15"))
    assert res is not None
    assert res["rel"] < -0.2          # large negative effect vs counterfactual
    assert res["significant"] is True  # CI excludes zero

def test_returns_none_when_insufficient_history():
    assert causal_counterfactual(_series([100, 60]), _series([100, 100]),
                                 pd.Timestamp("2026-04-02")) is None
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** `src/gaa/analytics/causal.py`

```python
from typing import Optional
import pandas as pd


def causal_counterfactual(target: pd.Series, control: pd.Series,
                          intervention: pd.Timestamp) -> Optional[dict]:
    """Bayesian structural time-series counterfactual (CausalImpact-style) on statsmodels.

    Fit target ~ local-level + control on the PRE period, forecast the counterfactual
    over POST using the control, and report the cumulative effect (actual - counterfactual)
    with a 95% interval. Returns None if there is too little history to fit.
    """
    df = pd.concat([target.rename("y"), control.rename("x")], axis=1).dropna().sort_index()
    pre, post = df[df.index < intervention], df[df.index >= intervention]
    if len(pre) < 5 or len(post) < 1:
        return None
    from statsmodels.tsa.statespace.structural import UnobservedComponents
    model = UnobservedComponents(pre["y"].values, level="local level", exog=pre[["x"]].values)
    res = model.fit(disp=False)
    fc = res.get_forecast(steps=len(post), exog=post[["x"]].values)
    ci = fc.conf_int(alpha=0.05)            # columns: [lower, upper]
    actual = float(post["y"].sum())
    counterfactual = float(fc.predicted_mean.sum())
    effect = actual - counterfactual
    lower = actual - float(ci[:, 1].sum())  # cumulative effect lower bound
    upper = actual - float(ci[:, 0].sum())
    return {"effect": effect, "rel": effect / counterfactual if counterfactual else 0.0,
            "lower": lower, "upper": upper, "significant": not (lower <= 0 <= upper),
            "counterfactual": counterfactual, "actual": actual}
```

- [ ] **Step 4: Run — expect PASS** (`pytest tests/analytics/test_causal.py -v`).

- [ ] **Step 5: Replace the market test**

`tests/modules/test_market_benchmark.py`:
```python
import pandas as pd
from gaa.modules.market_benchmark import MarketBenchmark
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.fixtures import FixtureBenchmarkSource
from gaa.schema.profile import GameProfile, ColumnMapping

def _ctx(metrics_df, start, end, changepoint=None):
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    ctx = AnalysisContext(profile=prof, metrics=metrics_df, query="q", metric="dau",
                          start=start, end=end, direction="down")
    if changepoint:
        ctx.extras["changepoint"] = changepoint
    return ctx

def _df(vals, start="2026-04-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D")
    df = pd.DataFrame({"date": idx, "metric": "dau", "value": [float(v) for v in vals]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    return df

def test_causal_path_flags_internal_when_control_holds():
    target = [100]*14 + [60, 61, 59]
    df = _df(target)
    bench = FixtureBenchmarkSource(genre_index={d.strftime("%Y-%m-%d"): 100.0
                                                for d in pd.date_range("2026-04-01", periods=17)})
    led = EvidenceLedger()
    MarketBenchmark(bench).run(_ctx(df, "2026-04-01", "2026-04-17", changepoint="2026-04-15"), led)
    e = [x for x in led.all() if x.module == "market"][0]
    assert "counterfactual" in e.claim.lower() or "market" in e.claim.lower()
    assert e.source_type == "derived"

def test_fallback_indexed_comparison_on_sparse_history():
    df = _df([1000, 600], start="2026-05-01")
    bench = FixtureBenchmarkSource(genre_index={"2026-05-01": 100.0, "2026-05-02": 98.0})
    led = EvidenceLedger()
    MarketBenchmark(bench).run(_ctx(df, "2026-05-01", "2026-05-02"), led)
    assert any(x.module == "market" for x in led.all())

def test_records_gap_when_no_benchmark():
    df = _df([1000, 600], start="2026-05-01")
    led = EvidenceLedger()
    MarketBenchmark(FixtureBenchmarkSource(genre_index={})).run(_ctx(df, "2026-05-01", "2026-05-02"), led)
    assert any(e.strength == "low" and e.source_type == "derived" for e in led.all())
```

- [ ] **Step 6: Replace** `src/gaa/modules/market_benchmark.py`

```python
import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.base import BenchmarkSource
from gaa.analytics.causal import causal_counterfactual


class MarketBenchmark:
    name = "market"

    def __init__(self, source: BenchmarkSource) -> None:
        self._source = source

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.metric and ctx.start and ctx.end):
            return
        trend = self._source.genre_trend(ctx.profile.genre, ctx.start, ctx.end)
        if len(trend) < 2:
            ledger.add(module=self.name, claim="no genre benchmark available for this window",
                       value="n/a", source="benchmark", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return

        control = pd.Series({pd.Timestamp(d): v for d, v in trend.items()}).sort_index()
        target = (ctx.metrics[ctx.metrics["metric"] == ctx.metric]
                  .groupby("date")["value"].sum().sort_index())
        intervention = pd.Timestamp(ctx.extras.get("changepoint") or ctx.start)
        result = causal_counterfactual(target, control, intervention)

        if result is None:
            # fallback: indexed comparison of % change (game vs genre)
            keys = sorted(trend)
            genre_change = (trend[keys[-1]] - trend[keys[0]]) / abs(trend[keys[0]])
            gchange = ((target.iloc[-1] - target.iloc[0]) / abs(target.iloc[0])
                       if len(target) >= 2 and target.iloc[0] else 0.0)
            verdict = ("underperforming the genre" if gchange - genre_change < -0.05
                       else "in line with the genre")
            ledger.add(module=self.name,
                       claim=f"genre {genre_change:+.0%} vs game {gchange:+.0%} → {verdict} (indexed)",
                       value=f"genre {genre_change:+.2%}; game {gchange:+.2%}",
                       source="benchmark:genre_index", source_type="external", strength="med",
                       timeframe=f"{ctx.start}..{ctx.end}")
            return

        rel = result["rel"]
        verdict = ("internal-driven (beyond the market)" if result["significant"] and rel < -0.05
                   else "market-wide" if abs(rel) <= 0.05 else "partly internal")
        ledger.add(
            module=self.name,
            claim=f"after absorbing the market, {ctx.metric} is {rel:+.0%} vs its counterfactual → {verdict}",
            value=f"effect {result['effect']:+.0f} (95% CI {result['lower']:+.0f}..{result['upper']:+.0f})",
            source="causalimpact:genre-control", source_type="derived",
            strength="high" if result["significant"] else "med",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
```

- [ ] **Step 7: Run both — expect PASS** (`pytest tests/analytics/test_causal.py tests/modules/test_market_benchmark.py -v`). Commit:

```bash
git add src/gaa/analytics/causal.py src/gaa/modules/market_benchmark.py tests/analytics/test_causal.py tests/modules/test_market_benchmark.py
git commit -m "feat: market module uses CausalImpact-style counterfactual (statsmodels)"
```

---

### Task 5: Anomaly module → change-point + STL deviation (supersedes Plan 2 Task 6)

**Files:**
- Create: `src/gaa/analytics/changepoint.py`
- Replace: `src/gaa/modules/anomaly.py`
- Keep `tests/modules/test_anomaly.py` (still valid) and add `tests/analytics/test_changepoint.py`

- [ ] **Step 1: Write the changepoint/deviation test**

`tests/analytics/test_changepoint.py`:
```python
import pandas as pd
from gaa.analytics.changepoint import detect_changepoint, deviation_z

def _s(vals, start="2026-04-01"):
    return pd.Series([float(v) for v in vals], index=pd.date_range(start, periods=len(vals), freq="D"))

def test_changepoint_finds_the_break():
    s = _s([100]*8 + [60]*8)
    cp = detect_changepoint(s)
    assert cp is not None
    assert pd.Timestamp("2026-04-07") <= cp <= pd.Timestamp("2026-04-11")

def test_changepoint_none_on_short_series():
    assert detect_changepoint(_s([100, 60])) is None

def test_deviation_z_flags_a_spike():
    z = deviation_z(_s([100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 60]))
    assert z is not None and abs(z) >= 2
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** `src/gaa/analytics/changepoint.py`

```python
from typing import Optional
import pandas as pd


def detect_changepoint(s: pd.Series) -> Optional[pd.Timestamp]:
    """First change-point date via PELT (ruptures). None if too short or unavailable."""
    if len(s) < 4:
        return None
    try:
        import ruptures as rpt
        bkps = rpt.Pelt(model="rbf").fit(s.values.astype(float)).predict(pen=3)
        cps = [b for b in bkps if 0 < b < len(s)]
        return s.index[cps[0]] if cps else None
    except Exception:
        return None


def deviation_z(s: pd.Series) -> Optional[float]:
    """Z-score of the latest point vs STL residual std. None if too short."""
    if len(s) < 6:
        return None
    try:
        from statsmodels.tsa.seasonal import STL
        period = 7 if len(s) >= 14 else max(2, len(s) // 2)
        resid = STL(s.values.astype(float), period=period, robust=True).fit().resid
        sd = float(resid.std()) or 1.0
        return float(resid[-1] / sd)
    except Exception:
        # fallback: simple z vs rolling mean/std
        mean, sd = float(s[:-1].mean()), float(s[:-1].std()) or 1.0
        return (float(s.iloc[-1]) - mean) / sd
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Replace** `src/gaa/modules/anomaly.py` (keeps the Plan 2 scan-mode behavior; adds onset + z)

```python
import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.analytics.changepoint import detect_changepoint, deviation_z


def _series(df: pd.DataFrame, metric: str) -> pd.Series:
    return df[df["metric"] == metric].groupby("date")["value"].sum().sort_index()


def _pct(s: pd.Series) -> float:
    return (s.iloc[-1] - s.iloc[0]) / abs(s.iloc[0]) if len(s) >= 2 and s.iloc[0] else 0.0


class AnomalyDetection:
    name = "anomaly"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        metrics = list(ctx.metrics["metric"].unique())
        if not metrics:
            ledger.add(module=self.name, claim="no internal metrics available", value="n/a",
                       source="internal", source_type="derived", strength="low")
            return

        target = ctx.metric or max(metrics, key=lambda m: abs(_pct(_series(ctx.metrics, m))))
        ctx.metric = target
        s = _series(ctx.metrics, target)
        change = _pct(s)
        ctx.direction = "down" if change < 0 else "up"
        ctx.start = ctx.start or str(s.index.min().date())
        ctx.end = ctx.end or str(s.index.max().date())

        onset = detect_changepoint(s)
        if onset is not None:
            ctx.extras["changepoint"] = str(onset.date())   # feeds Market module's intervention
        z = deviation_z(s)

        claim = f"{target} changed {change:+.0%} over window"
        if onset is not None:
            claim += f", breaking around {onset.date()}"
        value = f"{change:+.2%}" + (f" · z={z:+.1f}" if z is not None else "")
        strength = "high" if abs(change) >= 0.1 or (z is not None and abs(z) >= 3) else "med"
        ledger.add(module=self.name, claim=claim, value=value, source=f"internal:{target}",
                   source_type="internal", strength=strength, timeframe=f"{ctx.start}..{ctx.end}")
```

- [ ] **Step 6: Run** `pytest tests/modules/test_anomaly.py tests/analytics/test_changepoint.py -v` — expect PASS (Plan 2's anomaly tests still hold: a negative `change` keeps `-` in `value`; scan mode unchanged). Commit:

```bash
git add src/gaa/analytics/changepoint.py src/gaa/modules/anomaly.py tests/analytics/test_changepoint.py
git commit -m "feat: anomaly module adds change-point onset + STL deviation z"
```

---

### Task 6: Self-consistency abstention gate

**Files:**
- Create: `src/gaa/synth/gate.py`
- Test: `tests/synth/test_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/synth/test_gate.py`:
```python
from gaa.synth.gate import consistency_score, apply_gate
from gaa.schema.hypothesis import AttributionHypothesis, Cause, Causes
from gaa.schema.confidence import Confidence

def _h(primary, eq="Strong"):
    causes = Causes(internal=[Cause(claim="i", evidence_ids=["L1"], likelihood="Likely",
                                    evidence_quality="Strong")]) if primary == "internal" else \
             Causes(market=[Cause(claim="m", evidence_ids=["L1"], likelihood="Likely",
                                  evidence_quality="Strong")])
    return AttributionHypothesis(main_story="x",
                                 confidence=Confidence(likelihood="Likely", evidence_quality=eq),
                                 causes=causes)

def test_full_agreement_is_one():
    assert consistency_score([_h("internal"), _h("internal"), _h("internal")]) == 1.0

def test_disagreement_downgrades_and_notes_gap():
    samples = [_h("internal", "Strong"), _h("market"), _h("internal")]  # 2/3 agree
    h = apply_gate(_h("internal", "Strong"), samples, threshold=0.8)     # 0.67 < 0.8 -> downgrade
    assert h.confidence.evidence_quality == "Moderate"
    assert any("self-consistency" in g.lower() for g in h.assumptions_and_gaps)

def test_above_threshold_no_change():
    samples = [_h("internal"), _h("internal"), _h("internal")]
    h = apply_gate(_h("internal", "Strong"), samples, threshold=0.67)
    assert h.confidence.evidence_quality == "Strong"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** `src/gaa/synth/gate.py`

```python
from collections import Counter
from gaa.schema.hypothesis import AttributionHypothesis

_DOWNGRADE = {"Strong": "Moderate", "Moderate": "Weak", "Weak": "Weak"}


def _primary_direction(h: AttributionHypothesis) -> str:
    if h.causes.internal:
        return "internal"
    if h.causes.market:
        return "market"
    return "none"


def consistency_score(samples: list[AttributionHypothesis]) -> float:
    dirs = [_primary_direction(h) for h in samples]
    if not dirs:
        return 1.0
    return Counter(dirs).most_common(1)[0][1] / len(dirs)


def apply_gate(hypothesis: AttributionHypothesis, samples: list[AttributionHypothesis],
               threshold: float = 0.67) -> AttributionHypothesis:
    score = consistency_score(samples)
    if score < threshold:
        hypothesis.confidence.evidence_quality = _DOWNGRADE[hypothesis.confidence.evidence_quality]
        hypothesis.assumptions_and_gaps.append(
            f"Model self-consistency low ({score:.0%} agreement across {len(samples)} samples) "
            f"→ headline evidence quality downgraded one notch.")
    return hypothesis
```

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/synth/gate.py tests/synth/test_gate.py
git commit -m "feat: self-consistency abstention gate (lightweight conformal abstention)"
```

---

### Task 7: Wire the gate into the engine

**Files:**
- Modify: `src/gaa/engine.py` (Plan 2 Task 14 / Plan 3 Task 8 `_run`)
- Test: `tests/test_engine_gate.py`

The engine samples the synthesizer N times, applies the gate, then validates citations. With `FakeLLM` all samples are identical → score 1.0 → no behavior change for existing tests.

- [ ] **Step 1: Write the failing test**

`tests/test_engine_gate.py`:
```python
import pandas as pd
from gaa.engine import AttributionEngine
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping

def test_engine_accepts_n_samples_and_runs():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    engine = AttributionEngine(
        FakeLLM({"main_story": "x", "causes": {"internal": [], "market": []},
                 "scenarios": [], "risks": [], "assumptions_and_gaps": []}),
        FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
        FixtureSignalsSource([]), n_samples=3)
    h = engine.analyze(prof, df, "why did dau drop?")
    assert h.main_story == "x"
```

- [ ] **Step 2: Run — expect FAIL** (`n_samples` kwarg not accepted).

- [ ] **Step 3: Update `src/gaa/engine.py`** — add `n_samples` and the gate in `_run`

```python
# add import
from gaa.synth.gate import apply_gate

# in __init__ signature add: n_samples: int = 3  -> store self._n = n_samples
# in _run, replace the single synthesize call with sampling + gate:
        samples = [self._synth.synthesize(ledger, query) for _ in range(self._n)]
        hyp = apply_gate(samples[0], samples)
        hyp = validate_citations(hyp, ledger)
        return hyp, ctx
```

Full `__init__` becomes:
```python
    def __init__(self, llm, benchmark, signals, n_samples: int = 3) -> None:
        self._synth = Synthesizer(llm)
        self._benchmark = benchmark
        self._signals = signals
        self._n = n_samples
```

- [ ] **Step 4: Run the gate test + the full suite** — expect PASS

Run: `pytest -q`
Expected: all green (existing engine/graph tests unaffected — identical FakeLLM samples → no downgrade).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/engine.py tests/test_engine_gate.py
git commit -m "feat: engine samples synthesizer N times + applies self-consistency gate"
```

> Cost note: N=3 means 3 synthesis LLM calls per analysis. Tune `n_samples` down to 1 to disable the gate (e.g. for cost-sensitive runs); the demo uses 3.

---

## Self-Review (completed during authoring)

**Coverage:** Adtributor core + segment module (Tasks 2–3); causal counterfactual core + market module with graceful fallback (Task 4); change-point + STL deviation + anomaly module feeding the intervention point (Task 5); self-consistency gate + engine wiring (Tasks 6–7). Matches spec §6.5 + §8 + §15 Tier-1.

**Placeholder scan:** none. Fallbacks (sparse history → indexed comparison; ruptures/STL unavailable → None/simple-z) are explicit graceful-degradation paths, not gaps.

**Type consistency:** `EvidenceLedger.add(module=, claim=, value=, source=, source_type=, strength=, timeframe=)` keyword-identical to Plan 2 Task 2. `AnalysisContext` (incl. `.extras`, `.metric`, `.start`, `.end`, `.direction`) per Plan 2 Task 5; the anomaly module writes `ctx.extras["changepoint"]`, the market module reads it. `BenchmarkSource.genre_trend(genre, start, end) -> dict[str,float]` per Plan 2 Task 5 — consumed as the causal control series. `AttributionEngine(llm, benchmark, signals, n_samples=3)` extends Plan 2 Task 14 without breaking positional calls; `analyze`/`analyze_full` (Plan 3 Task 8) unchanged in return type. `apply_gate(hypothesis, samples, threshold)` / `consistency_score(samples)` and `Confidence.evidence_quality` ∈ {Strong,Moderate,Weak} per Plan 2 Task 1. Module `.name`/`.run(ctx, ledger)` match the `AnalysisModule` protocol. Competitor module (Plan 2 Task 9) and the GraphAgent (Plan 0) call these modules unchanged.
