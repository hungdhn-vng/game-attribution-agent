# Market & Social Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the GAA `market` and `signals` analysis legs into dynamic, cited, quantitative research — a percentile benchmark comparison plus influencer/social signals — so the agent can attribute a metric move to market-wide vs game-specific causes, including "are my users migrating to an influencer-boosted competitor?"

**Architecture:** Two web-research legs share one `research_json` helper (prompt → Perplexity → cited JSON → graceful `None`). Leg 1 (benchmark) is fetched in the pipeline crawl stage and read by `MarketBenchmark`; Leg 2 (social signals) runs in the modules stage via `CompetitorSignals`; a deterministic `MigrationPattern` detector reads the resulting ledger to assemble the migration hypothesis.

**Tech Stack:** Python 3.11, pandas, pydantic, sqlite3, httpx (Perplexity), pytest. Run tests with `.venv/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-14-market-and-social-research-design.md`

**Convention:** every commit message ends with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

**Milestone 1 — Quantitative benchmark**
- Create `src/gaa/core/crawl/research.py` — shared cited-JSON web-research helper.
- Modify `src/gaa/core/store/benchmark_store.py` — `put_benchmark`/`get_benchmark` (kind=`benchmark`, per metric).
- Modify `src/gaa/core/sources/providers/web.py` — `metric_benchmark()`.
- Modify `src/gaa/core/crawl/refresher.py` — `refresh(..., metric=None)` fetches+stores the benchmark.
- Modify `src/gaa/core/sources/dynamic.py` — `DynamicRefresher.refresh(..., metric=None)`.
- Modify `src/gaa/core/sources/crawling_benchmark.py` — `metric_benchmark()` read side.
- Modify `src/gaa/core/modules/market_benchmark.py` — emit the cited comparison entry.
- Modify `src/gaa/runs/pipeline.py` — `_stage_crawl` passes `metric`.

**Milestone 2 — Social signals + migration**
- Modify `src/gaa/core/schema/profile.py` — optional `title`.
- Create `src/gaa/core/sources/social_signals.py` — `SocialSignalProvider`.
- Modify `src/gaa/core/sources/dynamic.py` — `DynamicSignals` social wiring (+ injectable `answer_fn`).
- Modify `src/gaa/core/modules/competitor_signals.py` — scope/entity/reach enrichment + uses `profile.title`.
- Create `src/gaa/core/modules/migration.py` — `MigrationPattern` detector.
- Modify `src/gaa/runs/pipeline.py` — run `MigrationPattern` in `_stage_modules`.
- Create `src/gaa/core/crawl/roblox_title.py` — universe→title lookup; wire into onboarding.

---

# Milestone 1 — Quantitative benchmark

## Task 1: `research_json` shared helper

**Files:**
- Create: `src/gaa/core/crawl/research.py`
- Test: `tests/crawl/test_research.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/crawl/test_research.py
from gaa.core.crawl.research import research_json


def test_parses_object_and_attaches_citations():
    answer = lambda p: {"content": 'noise {"low": 12, "high": 19} tail',
                        "citations": [{"url": "https://x"}]}
    out = research_json(answer, "prompt")
    assert out["low"] == 12 and out["high"] == 19
    assert out["citations"] == [{"url": "https://x"}]


def test_returns_none_when_no_json():
    out = research_json(lambda p: {"content": "no json here", "citations": []}, "p")
    assert out is None


def test_returns_none_when_answer_fn_raises():
    def boom(p):
        raise RuntimeError("network down")
    assert research_json(boom, "p") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/crawl/test_research.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.core.crawl.research'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/core/crawl/research.py
"""Shared cited-JSON web-research helper.

answer_fn(prompt) -> {"content": str, "citations": list}. We extract the first
JSON object from the content, attach citations, and degrade to None on any
failure — research feeds are best-effort and must never crash a job.
"""
from __future__ import annotations

from typing import Callable, Optional

from gaa.core.llm.client import _extract_json


def research_json(answer_fn: Callable[[str], dict], prompt: str) -> Optional[dict]:
    try:
        ans = answer_fn(prompt)
        data = _extract_json(ans["content"])
        data["citations"] = ans.get("citations", [])
        return data
    except Exception:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/crawl/test_research.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/crawl/research.py tests/crawl/test_research.py
git commit -m "feat(crawl): research_json — shared cited-JSON web-research helper" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `BenchmarkStore.put_benchmark` / `get_benchmark`

**Files:**
- Modify: `src/gaa/core/store/benchmark_store.py`
- Test: `tests/store/test_benchmark_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_benchmark_store.py  (append)
def test_put_get_benchmark_per_metric(tmp_path):
    from gaa.core.store.benchmark_store import BenchmarkStore
    s = BenchmarkStore(str(tmp_path / "b.sqlite"))
    s.put_benchmark("roblox", "rpg", "retention_d1", {"low": 0.12, "high": 0.19})
    s.put_benchmark("roblox", "rpg", "retention_d7", {"low": 0.03, "high": 0.08})
    assert s.get_benchmark("roblox", "rpg", "retention_d1")["high"] == 0.19
    assert s.get_benchmark("roblox", "rpg", "retention_d7")["low"] == 0.03
    assert s.get_benchmark("roblox", "rpg", "dau") is None
    assert s.is_fresh("roblox", "rpg", "benchmark", 60.0) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/store/test_benchmark_store.py::test_put_get_benchmark_per_metric -v`
Expected: FAIL — `AttributeError: 'BenchmarkStore' object has no attribute 'put_benchmark'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/gaa/core/store/benchmark_store.py` after `get_qual` (around line 92):

```python
    def put_benchmark(self, platform: str, genre: str, metric: str, payload: dict) -> None:
        """Upsert a per-metric benchmark; multiple metrics coexist under one row."""
        existing = self._get(platform, genre, "benchmark") or {}
        existing.pop("fetched_at", None)
        existing[metric] = payload
        self._put(platform, genre, "benchmark", existing)

    def get_benchmark(self, platform: str, genre: str, metric: str) -> Optional[dict]:
        """Return the stored benchmark payload for one metric, or None."""
        payload = self._get(platform, genre, "benchmark")
        if payload is None:
            return None
        return payload.get(metric)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/store/test_benchmark_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/store/benchmark_store.py tests/store/test_benchmark_store.py
git commit -m "feat(store): per-metric benchmark put/get on BenchmarkStore" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `WebSearchBenchmarkProvider.metric_benchmark`

**Files:**
- Modify: `src/gaa/core/sources/providers/web.py`
- Test: `tests/sources/test_web_benchmark_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/sources/test_web_benchmark_provider.py
from gaa.core.sources.providers.web import WebSearchBenchmarkProvider


def _provider(payload_json, citations=None):
    return WebSearchBenchmarkProvider(
        lambda p: {"content": payload_json, "citations": citations or [{"url": "https://src"}]})


def test_percent_units_normalized_to_fraction_for_rate_metric():
    p = _provider('{"low": 12, "high": 19, "median": 15, "unit": "percent", '
                  '"source": "GA 2025", "confidence": "med"}')
    b = p.metric_benchmark("retention_d1", "rpg", "roblox", "2026-06-01", "2026-06-08")
    assert b["low"] == 0.12 and b["high"] == 0.19 and b["median"] == 0.15
    assert b["unit"] == "fraction" and b["source"] == "GA 2025"
    assert b["citations"] == [{"url": "https://src"}]


def test_unparseable_returns_none():
    assert _provider("not json").metric_benchmark(
        "retention_d1", "rpg", "roblox", "a", "b") is None


def test_missing_low_high_returns_none():
    assert _provider('{"source": "x"}').metric_benchmark(
        "retention_d1", "rpg", "roblox", "a", "b") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/sources/test_web_benchmark_provider.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'metric_benchmark'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/gaa/core/sources/providers/web.py` (new imports at top, new method on the class):

```python
from gaa.core.crawl.research import research_json
from gaa.core.analytics.aggregate import RATE_METRICS

_METRIC_LABELS = {
    "retention_d1": "Day 1 retention", "retention_d7": "Day 7 retention",
    "retention_d30": "Day 30 retention", "dau": "daily active users (DAU)",
    "mau": "monthly active users (MAU)", "arppu": "ARPPU", "arpdau": "ARPDAU",
    "revenue": "revenue", "sessions": "sessions per user",
    "playtime": "average session length",
}
```

```python
    def metric_benchmark(self, metric, genre, platform, start, end):
        """Return a cited benchmark range for `metric` in genre+platform, or None.

        Shape: {metric, low, high, median|None, unit, source, confidence,
        citations, summary}. Rate metrics are normalized to fractions.
        """
        label = _METRIC_LABELS.get(metric, metric)
        prompt = (
            f"What is the typical benchmark RANGE for {label} of {genre!r} games on "
            f"{platform!r} as of {start} to {end}? Prefer the 50th-90th percentile range. "
            'Respond ONLY with a JSON object {"low": number, "high": number, '
            '"median": number or null, "unit": "percent"|"fraction"|"raw", '
            '"source": short string, "confidence": "high"|"med"|"low", '
            '"summary": one short sentence}.'
        )
        data = research_json(self._answer_fn, prompt)
        if not data:
            return None
        try:
            low, high = float(data["low"]), float(data["high"])
        except (KeyError, TypeError, ValueError):
            return None
        median = data.get("median")
        try:
            median = float(median) if median not in (None, "") else None
        except (TypeError, ValueError):
            median = None
        is_rate = metric in RATE_METRICS
        if data.get("unit") == "percent" and is_rate:
            low, high = low / 100.0, high / 100.0
            median = median / 100.0 if median is not None else None
        return {
            "metric": metric, "low": low, "high": high, "median": median,
            "unit": "fraction" if is_rate else (data.get("unit") or "raw"),
            "source": data.get("source", ""), "confidence": data.get("confidence", "low"),
            "citations": data.get("citations", []), "summary": data.get("summary", ""),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/sources/test_web_benchmark_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/sources/providers/web.py tests/sources/test_web_benchmark_provider.py
git commit -m "feat(sources): WebSearchBenchmarkProvider.metric_benchmark — cited, unit-normalized range" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `BenchmarkRefresher.refresh(..., metric=)` fetches + stores benchmark

**Files:**
- Modify: `src/gaa/core/crawl/refresher.py`
- Test: `tests/crawl/test_refresher_benchmark.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/crawl/test_refresher_benchmark.py
from gaa.core.crawl.refresher import BenchmarkRefresher
from gaa.core.store.benchmark_store import BenchmarkStore


class _Web:
    def metric_benchmark(self, metric, genre, platform, start, end):
        return {"metric": metric, "low": 0.12, "high": 0.19, "source": "X",
                "confidence": "med", "citations": []}
    def qualitative(self, genre, platform, start, end):
        return None


def test_refresh_with_metric_stores_benchmark(tmp_path):
    store = BenchmarkStore(str(tmp_path / "b.sqlite"))
    ref = BenchmarkRefresher(store=store, providers_by_platform={}, web_provider=_Web())
    ref.refresh("roblox", "rpg", "2026-06-01", "2026-06-08", metric="retention_d1")
    b = store.get_benchmark("roblox", "rpg", "retention_d1")
    assert b is not None and b["high"] == 0.19


def test_refresh_without_metric_stores_no_benchmark(tmp_path):
    store = BenchmarkStore(str(tmp_path / "b.sqlite"))
    ref = BenchmarkRefresher(store=store, providers_by_platform={}, web_provider=_Web())
    ref.refresh("roblox", "rpg", "2026-06-01", "2026-06-08")
    assert store.get_benchmark("roblox", "rpg", "retention_d1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/crawl/test_refresher_benchmark.py -v`
Expected: FAIL — `TypeError: refresh() got an unexpected keyword argument 'metric'`

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/core/crawl/refresher.py`, change the `refresh` signature to accept `metric` and add the benchmark fetch at the very top of the method body (after the docstring, before the freshness short-circuit):

```python
    def refresh(
        self,
        platform: str,
        genre: str,
        start: str | None = None,
        end: str | None = None,
        deadline: float | None = None,
        metric: str | None = None,
    ) -> dict:
        # ── metric benchmark (independent side-store; best-effort) ────────────
        bench_fn = getattr(self._web_provider, "metric_benchmark", None)
        if (metric and bench_fn is not None
                and not self._store.is_fresh(platform, genre, "benchmark", self._ttl_s)):
            try:
                b = bench_fn(metric, genre, platform, start or "", end or "")
            except Exception:
                b = None
            if b:
                self._store.put_benchmark(platform, genre, metric, b)
        # ── existing quant/qual logic unchanged below ─────────────────────────
```

Leave the rest of `refresh` (the existing docstring, freshness short-circuit, quant providers, qual fallback, returns) exactly as-is below this block.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/crawl/test_refresher_benchmark.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/crawl/refresher.py tests/crawl/test_refresher_benchmark.py
git commit -m "feat(crawl): BenchmarkRefresher fetches+stores a per-metric benchmark" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `DynamicRefresher.refresh(..., metric=)` + pipeline passes metric

**Files:**
- Modify: `src/gaa/core/sources/dynamic.py:58-59`
- Modify: `src/gaa/runs/pipeline.py:171-186` (`_stage_crawl`)
- Test: `tests/runs/test_pipeline_crawl_metric.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runs/test_pipeline_crawl_metric.py
from gaa.core.sources.dynamic import DynamicRefresher


class _Cfg:
    def resolve(self, name):
        return ("snapshot", "default") if name == "benchmark_mode" else ("", "default")


class _Settings:
    cache_dir = "/tmp/gaa-test-cache"
    perplexity_api_key = ""


def test_dynamic_refresher_accepts_metric_kwarg():
    # snapshot mode → empty providers, no web; must accept metric without error
    r = DynamicRefresher(config=_Cfg(), settings=_Settings(), store=_FakeStore())
    out = r.refresh("roblox", "rpg", "2026-06-01", "2026-06-08", metric="retention_d1")
    assert isinstance(out, dict)


class _FakeStore:
    def is_fresh(self, *a, **k):
        return False
    def put_quant(self, *a, **k):
        pass
    def put_qual(self, *a, **k):
        pass
    def put_benchmark(self, *a, **k):
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runs/test_pipeline_crawl_metric.py -v`
Expected: FAIL — `TypeError: refresh() got an unexpected keyword argument 'metric'`

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/core/sources/dynamic.py`, update `DynamicRefresher.refresh`:

```python
    def refresh(self, platform, genre, start=None, end=None, deadline=None, metric=None) -> dict:
        return self._build().refresh(platform, genre, start, end, deadline=deadline, metric=metric)
```

In `src/gaa/runs/pipeline.py`, `_stage_crawl`, pass the metric (the `refresh(...)` call currently ends with `deadline=None,`):

```python
        info = self.refresher.refresh(
            state["platform"],
            state["genre"],
            state.get("start"),
            state.get("end"),
            deadline=None,  # refresher handles its own deadline internally
            metric=state.get("metric"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runs/test_pipeline_crawl_metric.py tests/runs/ -v`
Expected: PASS (new test + existing pipeline tests green)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/sources/dynamic.py src/gaa/runs/pipeline.py tests/runs/test_pipeline_crawl_metric.py
git commit -m "feat(pipeline): thread the analyzed metric into the benchmark refresh" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `CrawlingBenchmarkSource.metric_benchmark` (read side)

**Files:**
- Modify: `src/gaa/core/sources/crawling_benchmark.py`
- Test: `tests/sources/test_crawling_benchmark_metric.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/sources/test_crawling_benchmark_metric.py
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.store.benchmark_store import BenchmarkStore


def test_metric_benchmark_reads_store(tmp_path):
    store = BenchmarkStore(str(tmp_path / "b.sqlite"))
    store.put_benchmark("roblox", "rpg", "retention_d1", {"low": 0.12, "high": 0.19})
    src = CrawlingBenchmarkSource(store)
    src.set_platform("roblox")
    assert src.metric_benchmark("retention_d1", "rpg")["low"] == 0.12
    assert src.metric_benchmark("dau", "rpg") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/sources/test_crawling_benchmark_metric.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'metric_benchmark'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/gaa/core/sources/crawling_benchmark.py` after `qualitative_context`:

```python
    def metric_benchmark(self, metric: str, genre: str):
        """Return the stored per-metric benchmark for the active platform, or None."""
        return self._store.get_benchmark(self._platform, genre, metric)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/sources/test_crawling_benchmark_metric.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/sources/crawling_benchmark.py tests/sources/test_crawling_benchmark_metric.py
git commit -m "feat(sources): CrawlingBenchmarkSource.metric_benchmark read side" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `MarketBenchmark` emits the cited comparison entry

**Files:**
- Modify: `src/gaa/core/modules/market_benchmark.py`
- Test: `tests/modules/test_market_benchmark.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_market_benchmark.py  (append; reuses _ctx/_df from the file)
class _SourceWithBenchmark:
    def __init__(self, low, high):
        self._low, self._high = low, high
    def genre_trend(self, genre, start, end):
        return {}  # no quant trend → exercises only the benchmark path
    def metric_benchmark(self, metric, genre):
        return {"metric": metric, "low": self._low, "high": self._high,
                "median": None, "unit": "fraction", "source": "GA 2025",
                "confidence": "med", "citations": [{"url": "https://ga"}]}


def test_benchmark_comparison_flags_underperformance():
    from gaa.core.modules.market_benchmark import MarketBenchmark
    from gaa.core.modules.base import AnalysisContext
    from gaa.core.schema.ledger import EvidenceLedger
    df = _df([0.03, 0.034], start="2026-06-01")           # game ~3.4%
    df["metric"] = "retention_d1"
    ctx = _ctx(df, "2026-06-01", "2026-06-02")
    ctx.metric = "retention_d1"
    led = EvidenceLedger()
    MarketBenchmark(_SourceWithBenchmark(0.12, 0.19)).run(ctx, led)
    e = [x for x in led.all() if x.module == "market" and x.source_type == "external"
         and "benchmark" in x.claim.lower()][0]
    assert "underperform" in e.claim.lower()
    assert e.source == "https://ga"


def test_benchmark_comparison_in_line():
    from gaa.core.modules.market_benchmark import MarketBenchmark
    from gaa.core.modules.base import AnalysisContext
    from gaa.core.schema.ledger import EvidenceLedger
    df = _df([0.14, 0.15], start="2026-06-01")
    df["metric"] = "retention_d1"
    ctx = _ctx(df, "2026-06-01", "2026-06-02"); ctx.metric = "retention_d1"
    led = EvidenceLedger()
    MarketBenchmark(_SourceWithBenchmark(0.12, 0.19)).run(ctx, led)
    assert any("in line" in x.claim.lower() for x in led.all() if x.module == "market")
```

Note: `_df` sets `metric="dau"`; the test overrides the column to `retention_d1` and sets `ctx.metric` so the rate-percentage formatting path is exercised.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/modules/test_market_benchmark.py::test_benchmark_comparison_flags_underperformance -v`
Expected: FAIL — no external "benchmark" entry is produced (IndexError on the list access).

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/core/modules/market_benchmark.py`: add imports, call a new guarded method at the end of `run`, and implement it.

At the top:

```python
from gaa.core.analytics.aggregate import metric_series, RATE_METRICS
```

At the end of `MarketBenchmark.run(...)` (after the existing CausalImpact/indexed block), add:

```python
        self._emit_benchmark_comparison(ctx, ledger)
```

Add the method:

```python
    def _emit_benchmark_comparison(self, ctx, ledger):
        fn = getattr(self._source, "metric_benchmark", None)
        if fn is None:
            return
        try:
            b = fn(ctx.metric, ctx.profile.genre)
            if not b:
                return
            s = metric_series(ctx.metrics, ctx.metric)
            if s.empty:
                return
            g, low, high = float(s.iloc[-1]), float(b["low"]), float(b["high"])
            if g < low:
                verdict = "underperforming the market"
            elif g > high:
                verdict = "outperforming the market"
            else:
                verdict = "in line with the market"
            rate = ctx.metric in RATE_METRICS
            fmt = (lambda x: f"{x:.1%}") if rate else (lambda x: f"{x:,.0f}")
            cites = b.get("citations") or []
            first = cites[0] if cites else None
            src = ((first.get("url") if isinstance(first, dict) else first)
                   or b.get("source") or "benchmark")
            strength = "low" if (b.get("confidence") == "low" or not cites) else "med"
            ledger.add(
                module=self.name,
                claim=(f"{ctx.metric} ≈ {fmt(g)} vs {ctx.profile.genre} benchmark "
                       f"{fmt(low)}–{fmt(high)} → {verdict}"),
                value=f"game {fmt(g)}; benchmark {fmt(low)}–{fmt(high)} ({b.get('confidence','low')})",
                source=src, source_type="external", strength=strength,
                timeframe=f"{ctx.start}..{ctx.end}",
            )
        except Exception:
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/modules/test_market_benchmark.py -v`
Expected: PASS (new tests + all existing market tests green — `FixtureBenchmarkSource` has no `metric_benchmark`, so the guard skips it)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/market_benchmark.py tests/modules/test_market_benchmark.py
git commit -m "feat(market): cited benchmark comparison (game value vs genre percentile range)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Full suite regression**

Run: `.venv/bin/python -m pytest -q`
Expected: all green. **Milestone 1 complete.**

---

# Milestone 2 — Social signals + migration

## Task 8: Optional `GameProfile.title`

**Files:**
- Modify: `src/gaa/core/schema/profile.py:23-29`
- Test: `tests/schema/test_profile_title.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/schema/test_profile_title.py
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _mapping():
    return ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={})


def test_title_defaults_to_none_and_round_trips():
    p = GameProfile(name="csv-key", platform="roblox", genre="rpg", mapping=_mapping())
    assert p.title is None
    p2 = GameProfile.model_validate_json(
        GameProfile(name="csv-key", platform="roblox", genre="rpg",
                    mapping=_mapping(), title="Real Game Name").model_dump_json())
    assert p2.title == "Real Game Name"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/schema/test_profile_title.py -v`
Expected: FAIL — `AttributeError: 'GameProfile' object has no attribute 'title'`

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/core/schema/profile.py`, add the field and import `Optional`:

```python
from typing import Optional
```

```python
class GameProfile(BaseModel):
    name: str
    platform: str
    genre: str
    mapping: ColumnMapping
    title: Optional[str] = None  # real game title for web/social research (name is a CSV key)
    external_source_config: dict = {}
    created_at: str = Field(default_factory=_now_iso)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/schema/test_profile_title.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/schema/profile.py tests/schema/test_profile_title.py
git commit -m "feat(schema): optional GameProfile.title for web/social research" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `SocialSignalProvider`

**Files:**
- Create: `src/gaa/core/sources/social_signals.py`
- Test: `tests/sources/test_social_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/sources/test_social_signals.py
from gaa.core.sources.social_signals import SocialSignalProvider

_JSON = ('{"signals": ['
         '{"date": "2026-06-04", "kind": "influencer", "scope": "game", '
         '"entity": "BigTuber (3M)", "reach": "1.2M views", "url": "https://yt", '
         '"summary": "featured the game", "sentiment": 0.5},'
         '{"date": "2026-05-01", "kind": "social_trend", "scope": "genre", '
         '"entity": "TikTok", "reach": "", "url": "https://tt", '
         '"summary": "genre buzz", "sentiment": 0.1}]}')


def test_parses_and_window_filters():
    prov = SocialSignalProvider(lambda p: {"content": _JSON, "citations": []})
    out = prov.events("Real Game", "rpg", "2026-06-01", "2026-06-08")
    assert len(out) == 1                       # the 05-01 genre signal is out of window
    ev = out[0]
    assert ev["kind"] == "influencer" and ev["scope"] == "game"
    assert ev["entity"] == "BigTuber (3M)" and ev["url"] == "https://yt"
    assert ev["title"]                         # title populated for CompetitorSignals


def test_unparseable_returns_empty_list():
    assert SocialSignalProvider(lambda p: {"content": "nope", "citations": []}).events(
        "g", "rpg", "2026-06-01", "2026-06-08") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/sources/test_social_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.core.sources.social_signals'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/core/sources/social_signals.py
"""Perplexity-backed influencer / social-trend signal provider.

Implements the SignalsSource protocol: events(game, genre, start, end) -> list.
Each event is a superset of the legacy {date,title,kind,url,sentiment} shape plus
scope/entity/reach, so CompetitorSignals consumes it unchanged.
"""
from __future__ import annotations

from typing import Callable

from gaa.core.crawl.research import research_json


class SocialSignalProvider:
    def __init__(self, answer_fn: Callable[[str], dict], platform: str = "") -> None:
        self._answer_fn = answer_fn
        self._platform = platform

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        plat = f" on {self._platform}" if self._platform else ""
        game_clause = (f'for the game "{game}" specifically (influencer/YouTuber/TikTok '
                       f'coverage, viral moments), and ' if game else "")
        prompt = (
            f"Between {start} and {end}, what influencer or social-media activity affected "
            f"the {genre!r} game genre{plat}? Look {game_clause}for COMPETING games in this "
            f"genre that gained players or attention in this window and whether an influencer "
            f"drove it (name the game, the influencer/channel, and the date). "
            'Respond ONLY with a JSON object {"signals": [ '
            '{"date": "YYYY-MM-DD", "kind": "influencer"|"social_trend"|"competitor_event", '
            '"scope": "game"|"genre", "entity": str, "reach": str, "url": str, '
            '"summary": str, "sentiment": number between -1 and 1} ]}.'
        )
        data = research_json(self._answer_fn, prompt)
        if not data:
            return []
        out = []
        for s in data.get("signals", []) or []:
            d = s.get("date")
            if not d or not (start <= d <= end):
                continue
            try:
                sentiment = float(s.get("sentiment", 0) or 0)
            except (TypeError, ValueError):
                sentiment = 0.0
            out.append({
                "date": d,
                "kind": s.get("kind", "social_trend"),
                "scope": s.get("scope", "genre"),
                "entity": s.get("entity", ""),
                "reach": s.get("reach", ""),
                "url": s.get("url", ""),
                "summary": s.get("summary", ""),
                "sentiment": sentiment,
                "title": s.get("summary") or s.get("entity") or s.get("kind", "signal"),
            })
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/sources/test_social_signals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/sources/social_signals.py tests/sources/test_social_signals.py
git commit -m "feat(sources): SocialSignalProvider — cited influencer/social signals (game+genre)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `DynamicSignals` social wiring (injectable `answer_fn`)

**Files:**
- Modify: `src/gaa/core/sources/dynamic.py:62-74`
- Test: `tests/sources/test_dynamic_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/sources/test_dynamic_signals.py
from gaa.core.sources.dynamic import DynamicSignals

_JSON = ('{"signals": [{"date": "2026-06-04", "kind": "influencer", "scope": "game", '
         '"entity": "T", "reach": "1M", "url": "https://x", "summary": "s", '
         '"sentiment": 0.3}]}')


class _Cfg:
    def __init__(self, mode):
        self._mode = mode
    def resolve(self, name):
        if name == "benchmark_mode":
            return (self._mode, "store")
        return ("", "default")


class _Settings:
    cache_dir = "/tmp/gaa-test-cache"
    perplexity_api_key = "k"


def test_uses_social_provider_when_crawl_mode():
    ds = DynamicSignals(config=_Cfg("crawl"), settings=_Settings(),
                        answer_fn=lambda p: {"content": _JSON, "citations": []})
    out = ds.events("Real Game", "rpg", "2026-06-01", "2026-06-08")
    assert out and out[0]["kind"] == "influencer"


def test_falls_back_to_fixture_when_not_crawl():
    ds = DynamicSignals(config=_Cfg("snapshot"), settings=_Settings(),
                        answer_fn=lambda p: {"content": _JSON, "citations": []})
    assert ds.events("g", "rpg", "2026-06-01", "2026-06-08") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/sources/test_dynamic_signals.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'answer_fn'`

- [ ] **Step 3: Write minimal implementation**

Replace `DynamicSignals` in `src/gaa/core/sources/dynamic.py`:

```python
class DynamicSignals:
    """SignalsSource facade that honors the live config on each call."""

    def __init__(self, config, settings: Settings, answer_fn=None) -> None:
        self._config = config
        self._settings = settings
        self._answer_fn = answer_fn  # injectable for tests; prod builds perplexity_answer

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        if (self._config.resolve("benchmark_mode")[0] == "crawl"
                and (self._answer_fn or self._settings.perplexity_api_key)):
            from gaa.core.sources.social_signals import SocialSignalProvider
            answer_fn = self._answer_fn
            if answer_fn is None:
                from gaa.core.crawl.perplexity import perplexity_answer
                answer_fn = lambda p: perplexity_answer(p, self._settings)
            return SocialSignalProvider(answer_fn).events(game, genre, start, end)
        tmpl = self._config.resolve("signals_url_tmpl")[0]
        src = (WebSignalsSource(cache_dir=self._settings.cache_dir + "/signals",
                                query_url_tmpl=tmpl)
               if tmpl else FixtureSignalsSource([]))
        return src.events(game, genre, start, end)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/sources/test_dynamic_signals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/sources/dynamic.py tests/sources/test_dynamic_signals.py
git commit -m "feat(sources): DynamicSignals uses SocialSignalProvider in crawl mode (injectable answer_fn)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: `CompetitorSignals` scope/entity enrichment + uses `profile.title`

**Files:**
- Modify: `src/gaa/core/modules/competitor_signals.py`
- Test: `tests/modules/test_competitor_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_competitor_signals.py
import pandas as pd
from gaa.core.modules.competitor_signals import CompetitorSignals
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _ctx(title=None):
    prof = GameProfile(name="csv-key", platform="roblox", genre="rpg", title=title,
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    df = pd.DataFrame({"date": pd.to_datetime(["2026-06-04"]), "metric": ["dau"], "value": [1.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-06-01", end="2026-06-08")


class _Src:
    def __init__(self, events, recorder=None):
        self._events, self._rec = events, recorder
    def events(self, game, genre, start, end):
        if self._rec is not None:
            self._rec.append(game)
        return self._events


def test_game_scoped_influencer_becomes_external_entry():
    ev = [{"date": "2026-06-04", "kind": "influencer", "scope": "game",
           "entity": "BigTuber", "reach": "1.2M", "url": "https://yt",
           "summary": "featured the game", "sentiment": 0.5, "title": "featured the game"}]
    led = EvidenceLedger()
    CompetitorSignals(_Src(ev)).run(_ctx(), led)
    e = [x for x in led.all() if x.module == "competitor"][0]
    assert e.source_type == "external" and "(influencer)" in e.claim
    assert "BigTuber" in e.claim and e.source == "https://yt"


def test_passes_profile_title_to_source():
    rec = []
    CompetitorSignals(_Src([], recorder=rec)).run(_ctx(title="Real Game Name"), EvidenceLedger())
    assert rec == ["Real Game Name"]


def test_legacy_event_without_scope_keeps_old_format():
    ev = [{"date": "2026-06-04", "kind": "patch", "title": "v2 released",
           "url": "https://u", "sentiment": 0.0}]
    led = EvidenceLedger()
    CompetitorSignals(_Src(ev)).run(_ctx(), led)
    assert any(x.claim == "patch: v2 released" for x in led.all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/modules/test_competitor_signals.py -v`
Expected: FAIL — `test_game_scoped_influencer...` (no `(influencer)` in claim) and `test_passes_profile_title...` (passes `csv-key`, not the title).

- [ ] **Step 3: Write minimal implementation**

Replace the body of `CompetitorSignals.run` in `src/gaa/core/modules/competitor_signals.py`. Update `_STRENGTH_BY_KIND`, pass the title, and branch on `scope`:

```python
_STRENGTH_BY_KIND = {"patch": "high", "competitor": "med", "competitor_event": "med",
                     "news": "med", "influencer": "med", "social": "low", "social_trend": "low"}


class CompetitorSignals:
    name = "competitor"

    def __init__(self, source) -> None:
        self._source = source

    def run(self, ctx, ledger) -> None:
        if not (ctx.start and ctx.end):
            return
        game = getattr(ctx.profile, "title", None) or ctx.profile.name
        try:
            events = self._source.events(game, ctx.profile.genre, ctx.start, ctx.end)
        except Exception as exc:
            ledger.add(module=self.name, claim=f"signal feed unavailable ({type(exc).__name__})",
                       value="n/a", source="signals", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        if not events:
            ledger.add(module=self.name, claim="no external competitor/event signals found in window",
                       value="0 events", source="signals", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        for ev in events:
            kind = ev.get("kind", "social")
            scope = ev.get("scope")
            if scope == "game":
                claim = (f"external ({kind}): {ev.get('entity', '')} on {ev['date']} "
                         f"(reach {ev.get('reach', '?')}) — may explain the "
                         f"{ctx.metric or 'metric'} move: {ev.get('title', '')}")
                strength = ("high" if kind in ("influencer", "competitor_event") and ev.get("reach")
                            else _STRENGTH_BY_KIND.get(kind, "low"))
            elif scope == "genre":
                claim = f"genre social trend ({kind}): {ev.get('title', '')}"
                strength = _STRENGTH_BY_KIND.get(kind, "low")
            else:
                claim = f"{kind}: {ev['title']}"  # legacy shape, unchanged
                strength = _STRENGTH_BY_KIND.get(kind, "low")
            ledger.add(module=self.name, claim=claim,
                       value=f"sentiment {ev.get('sentiment', 0):+.2f}",
                       source=ev.get("url", "signals"), source_type="external",
                       strength=strength, timeframe=ev["date"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/modules/test_competitor_signals.py tests/cli/test_primitives.py -v`
Expected: PASS (new tests + existing `test_signals_appends_entry` green)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/competitor_signals.py tests/modules/test_competitor_signals.py
git commit -m "feat(signals): scope/entity/reach enrichment + use profile.title" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: `MigrationPattern` detector

**Files:**
- Create: `src/gaa/core/modules/migration.py`
- Test: `tests/modules/test_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_migration.py
import pandas as pd
from gaa.core.modules.migration import MigrationPattern
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _ctx(changepoint="2026-06-05"):
    prof = GameProfile(name="g", platform="roblox", genre="rpg",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    df = pd.DataFrame({"date": pd.to_datetime(["2026-06-04"]), "metric": ["dau"], "value": [1.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    ctx = AnalysisContext(profile=prof, metrics=df, query="q", metric="retention_d1",
                          start="2026-06-01", end="2026-06-08")
    ctx.extras["changepoint"] = changepoint
    return ctx


def _seed(led, *, market_claim, signal_claim, signal_date="2026-06-04"):
    led.add(module="market", claim=market_claim, value="v", source="b",
            source_type="external", strength="med", timeframe="2026-06-01..2026-06-08")
    led.add(module="competitor", claim=signal_claim, value="v", source="https://yt",
            source_type="external", strength="med", timeframe=signal_date)


def test_emits_migration_when_pattern_present():
    led = EvidenceLedger()
    _seed(led, market_claim="retention_d1 ≈ 3% vs rpg benchmark 12%–19% → underperforming the market",
          signal_claim="external (influencer): BigTuber on 2026-06-04 — may explain the move: X blew up")
    MigrationPattern().run(_ctx(), led)
    m = [e for e in led.all() if e.module == "migration"]
    assert m and "migration" in m[0].claim.lower() and m[0].source_type == "derived"
    assert m[0].strength == "med"  # timing near change-point


def test_no_migration_without_competitor_signal():
    led = EvidenceLedger()
    _seed(led, market_claim="… underperforming the market",
          signal_claim="genre social trend (social_trend): generic buzz")  # not influencer/competitor_event
    MigrationPattern().run(_ctx(), led)
    assert not [e for e in led.all() if e.module == "migration"]


def test_no_migration_without_game_specific_market():
    led = EvidenceLedger()
    _seed(led, market_claim="genre trending flat",
          signal_claim="external (influencer): BigTuber on 2026-06-04 — X blew up")
    MigrationPattern().run(_ctx(), led)
    assert not [e for e in led.all() if e.module == "migration"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/modules/test_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.core.modules.migration'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/core/modules/migration.py
"""Deterministic migration-hypothesis detector.

Reads the ledger after market + competitor have run. If a game-specific decline
coincides with an influencer/competitor surge near the change-point, it adds a
single derived "likely player migration" entry — with the standing caveat that
user-level migration is unconfirmed without cross-game data.
"""
from __future__ import annotations

from datetime import date

from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger


def _within_days(a: str, b: str, n: int) -> bool:
    try:
        da, db = date.fromisoformat(a[:10]), date.fromisoformat(b[:10])
    except (ValueError, TypeError):
        return False
    return abs((da - db).days) <= n


class MigrationPattern:
    name = "migration"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        entries = ledger.all()
        game_specific = any(
            e.module == "market"
            and ("underperform" in e.claim.lower() or "internal-driven" in e.claim.lower())
            for e in entries)
        competitor = next(
            (e for e in entries
             if e.module == "competitor" and e.source_type == "external"
             and ("(influencer)" in e.claim or "(competitor_event)" in e.claim)),
            None)
        if not (game_specific and competitor):
            return
        cp = ctx.extras.get("changepoint")
        near = bool(cp and competitor.timeframe and _within_days(competitor.timeframe, cp, 3))
        ledger.add(
            module=self.name,
            claim=("likely player migration — a game-specific decline coincides with an "
                   f"influencer/competitor surge ({competitor.claim[:90]}). "
                   "Caveat: user-level migration unconfirmed without cross-game data."),
            value="timing aligns with change-point" if near else "timing approximate",
            source=competitor.source, source_type="derived",
            strength="med" if near else "low",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/modules/test_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/modules/migration.py tests/modules/test_migration.py
git commit -m "feat(migration): detector for influencer-driven competitor migration hypothesis" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Run `MigrationPattern` in the pipeline modules stage

**Files:**
- Modify: `src/gaa/runs/pipeline.py:30` (import) and `:214-216` (`_stage_modules`)
- Test: `tests/runs/test_pipeline_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runs/test_pipeline_migration.py
import inspect
from gaa.runs import pipeline


def test_pipeline_runs_migration_pattern():
    src = inspect.getsource(pipeline.AnalysisPipeline._stage_modules)
    assert "MigrationPattern" in src, "modules stage must run MigrationPattern after competitor"
    assert "from gaa.core.modules.migration import MigrationPattern" in inspect.getsource(pipeline)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runs/test_pipeline_migration.py -v`
Expected: FAIL — `MigrationPattern` not referenced in the pipeline source.

- [ ] **Step 3: Write minimal implementation**

In `src/gaa/runs/pipeline.py`, add the import near the other module imports (line ~30):

```python
from gaa.core.modules.migration import MigrationPattern
```

In `_stage_modules`, after the `CompetitorSignals(self.signals).run(ctx, ledger)` line:

```python
        SegmentDecomposition().run(ctx, ledger)
        MarketBenchmark(self.benchmark).run(ctx, ledger)
        CompetitorSignals(self.signals).run(ctx, ledger)
        MigrationPattern().run(ctx, ledger)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runs/test_pipeline_migration.py tests/runs/ -v`
Expected: PASS (new test + existing pipeline tests green)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/runs/pipeline.py tests/runs/test_pipeline_migration.py
git commit -m "feat(pipeline): run MigrationPattern after market+competitor in modules stage" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Roblox universe→title lookup + onboarding wiring

**Files:**
- Create: `src/gaa/core/crawl/roblox_title.py`
- Modify: `src/gaa/cli/commands/onboarding.py` (set `title` on confirm when a universe id is present)
- Test: `tests/crawl/test_roblox_title.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/crawl/test_roblox_title.py
from gaa.core.crawl.roblox_title import universe_id_from, lookup_universe_title


def test_extracts_universe_id_from_csv_key():
    assert universe_id_from("Universe-9980885306- Day 1 retention …") == "9980885306"
    assert universe_id_from("no id here") is None


def test_lookup_uses_injected_fetcher():
    body = '{"data": [{"name": "[ALPHA] UGC Anime Face Creator"}]}'
    title = lookup_universe_title("9980885306", fetch_fn=lambda url: body)
    assert title == "[ALPHA] UGC Anime Face Creator"


def test_lookup_returns_none_on_failure():
    def boom(url):
        raise RuntimeError("offline")
    assert lookup_universe_title("123", fetch_fn=boom) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/crawl/test_roblox_title.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaa.core.crawl.roblox_title'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gaa/core/crawl/roblox_title.py
"""Resolve a Roblox universe id (often embedded in a CSV key) to its real game title."""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

import httpx

_UNIVERSE_RE = re.compile(r"universe[-_\s]*(\d{5,})", re.IGNORECASE)
_GAMES_URL = "https://games.roblox.com/v1/games?universeIds={id}"


def universe_id_from(text: str) -> Optional[str]:
    m = _UNIVERSE_RE.search(text or "")
    return m.group(1) if m else None


def _default_fetch(url: str) -> str:
    return httpx.get(url, headers={"Accept": "application/json"}, timeout=15.0).text


def lookup_universe_title(universe_id: str,
                          fetch_fn: Optional[Callable[[str], str]] = None) -> Optional[str]:
    fetch = fetch_fn or _default_fetch
    try:
        data = json.loads(fetch(_GAMES_URL.format(id=universe_id)))
        rows = data.get("data") or []
        return rows[0].get("name") if rows else None
    except Exception:
        return None
```

In `src/gaa/cli/commands/onboarding.py`, inside `cmd_onboard_confirm`, after the `GameProfile` is built and before it is saved, set the title best-effort (do not let a failed lookup block onboarding):

```python
    from gaa.core.crawl.roblox_title import universe_id_from, lookup_universe_title
    if getattr(profile, "title", None) is None and profile.platform == "roblox":
        uid = universe_id_from(profile.name)
        if uid:
            profile.title = lookup_universe_title(uid)  # None on failure → genre-scoped fallback
```

(Adapt the variable name `profile` to the actual local in `cmd_onboard_confirm`; if the profile is constructed inline in the save call, hoist it to a local first.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/crawl/test_roblox_title.py tests/cli/test_onboarding.py -v`
Expected: PASS (new tests + existing onboarding tests green)

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/crawl/roblox_title.py src/gaa/cli/commands/onboarding.py tests/crawl/test_roblox_title.py
git commit -m "feat(onboarding): resolve Roblox universe id to real game title for social research" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Full suite regression**

Run: `.venv/bin/python -m pytest -q`
Expected: all green. **Milestone 2 complete.**

---

## Self-review checklist (completed during plan authoring)

- **Spec coverage:** §5.1→T1, §5.2→T3, §5.3→T2, §5.4→T4, §5.5→T5, §5.6→T6, §5.7→T7, §5.8→T9, §5.9→T10, §5.10→T11, §5.11→T12 (+T13 wiring), §5.12→T8+T14. Migration sharpening (§7) → T12. ✅
- **Placeholder scan:** every code step has complete code; the only adaptation note is T14 step 3 (`profile` local name in `cmd_onboard_confirm`), which the executor confirms against the real handler. No TODO/TBD.
- **Type consistency:** event dict keys (`date/kind/scope/entity/reach/url/summary/sentiment/title`) are identical across T9 (producer), T11 (consumer), T12 (detector matches `(influencer)`/`(competitor_event)` substrings emitted by T11). Benchmark dict keys (`metric/low/high/median/unit/source/confidence/citations`) identical across T3 (producer), T2 (store), T7 (consumer). `refresh(..., metric=)` consistent across T4/T5.

## Notes / deferred
- Social-signal caching (spec §9, ~24h TTL) is **not** implemented in these tasks — each analysis re-calls Perplexity. Add a `CachedFetcher`-backed cache keyed by `(game, genre, start, end)` as a fast follow if call volume matters.
- The remaining unguarded `causal_counterfactual` call in `MarketBenchmark` (Bug 6) is out of scope here; the new benchmark-comparison block (T7) is independently guarded.
