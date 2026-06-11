# Game Attribution Agent — Plan 3: Onboarding UX, Report Renderer & Demo

> ⚠️ **RECONCILED BY [Plan 0 — AgentBase + LangGraph Integration](2026-06-11-game-attribution-agent-plan-0-agentbase-langgraph-integration.md).** This plan's pure-logic tasks (1–4, 6, 7: cached fetcher, live RoMonitor benchmark, live web signals, `Profiler`, Plotly charts, HTML `render_report`) **remain valid as written.** **Superseded:** Tasks 5, 8, 9 (FastAPI `/onboard`, `/analyze` html, `/chat` routes → LangGraph nodes in Plan 0; the handlers `Profiler`, `render_report`, `classify_intent`, `to_markdown` are reused verbatim). **Amended:** Task 10 (FastAPI `/demo` + live wiring + README → Plan 0 Tasks 8–9). See Plan 0's supersession map.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent end-to-end usable and demo-ready: a cached web crawler that backs the external `BenchmarkSource`/`SignalsSource` interfaces with live Roblox-ecosystem data; chat-assisted onboarding that turns an uploaded CSV / Roblox export into a confirmed `GameProfile` + ingested metrics; a self-contained interactive HTML report (4 Plotly charts) returned from `/analyze`; a single `/chat` entry that routes setup vs analysis; plus a pre-baked demo snapshot, README, and form summary.

**Architecture:** Builds on Plan 1 (data layer, API) + Plan 2 (engine, sources interfaces, synthesizer). A `CachedFetcher` (disk cache, injectable fetch fn) powers `RoMonitorBenchmark` and `WebSignalsSource`, both implementing the Plan 2 source protocols — so the engine swaps from fixtures to live data with no module change. A `Profiler` (LLM, injectable) proposes a `ColumnMapping`; onboarding endpoints persist a `GameProfile` (Plan 1) + write canonical metrics to `MetricsStore` (Plan 2). The `report` renderer builds 4 Plotly figures (inline JS, self-contained) into a Jinja2 template; `/analyze` returns the real `html`. A pre-baked snapshot guarantees a clean demo run.

**Tech Stack:** Python 3.11, httpx, beautifulsoup4, plotly, jinja2, FastAPI, pytest.

**Dependency note:** Requires Plans 1 & 2 merged. Live endpoints (RoMonitor/Rolimon's, news/social) must be confirmed at build time — each live source takes an injected `fetch` so all tests run offline against canned payloads.

---

### Task 1: Cached fetcher

**Files:**
- Create: `src/gaa/crawl/__init__.py` (empty)
- Create: `src/gaa/crawl/cache.py`
- Create: `src/gaa/crawl/fetcher.py`
- Test: `tests/crawl/test_fetcher.py`
- Create: `tests/crawl/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/crawl/test_fetcher.py`:
```python
from gaa.crawl.fetcher import CachedFetcher

def test_caches_after_first_fetch(tmp_path):
    calls = {"n": 0}
    def fake_fetch(url):
        calls["n"] += 1
        return f"body for {url}"
    f = CachedFetcher(cache_dir=str(tmp_path), fetch_fn=fake_fetch)
    assert f.get("http://x") == "body for http://x"
    assert f.get("http://x") == "body for http://x"
    assert calls["n"] == 1  # second call served from cache

def test_falls_back_to_cache_on_fetch_error(tmp_path):
    state = {"fail": False}
    def fake_fetch(url):
        if state["fail"]:
            raise RuntimeError("network down")
        return "live"
    f = CachedFetcher(cache_dir=str(tmp_path), fetch_fn=fake_fetch)
    assert f.get("http://x") == "live"   # populates cache
    state["fail"] = True
    assert f.get("http://x") == "live"   # replays from cache despite error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/crawl/test_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/gaa/crawl/cache.py`**

```python
import hashlib
import os


class DiskCache:
    def __init__(self, cache_dir: str) -> None:
        self._dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        h = hashlib.sha256(key.encode()).hexdigest()[:32]
        return os.path.join(self._dir, f"{h}.txt")

    def get(self, key: str) -> str | None:
        p = self._path(key)
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None

    def put(self, key: str, value: str) -> None:
        with open(self._path(key), "w", encoding="utf-8") as fh:
            fh.write(value)
```

- [ ] **Step 4: Write `src/gaa/crawl/fetcher.py`**

```python
from typing import Callable, Optional
from gaa.crawl.cache import DiskCache


def _http_get(url: str) -> str:
    import httpx
    r = httpx.get(url, timeout=20, headers={"User-Agent": "gaa-bot/0.1"})
    r.raise_for_status()
    return r.text


class CachedFetcher:
    """Fetch with read-through disk cache; replay cache on fetch failure."""
    def __init__(self, cache_dir: str, fetch_fn: Optional[Callable[[str], str]] = None) -> None:
        self._cache = DiskCache(cache_dir)
        self._fetch = fetch_fn or _http_get

    def get(self, url: str) -> str:
        cached = self._cache.get(url)
        try:
            body = self._fetch(url)
            self._cache.put(url, body)
            return body
        except Exception:
            if cached is not None:
                return cached
            raise
```

> Note: cache is read-through but **refreshes** on success; on failure it replays. `test_caches_after_first_fetch` asserts one network call for two reads — make `get` return the cached value WITHOUT re-fetching when present. Adjust: check cache first and return it directly; only fetch on miss; keep the failure-replay path. Final `get`:
> ```python
> def get(self, url: str) -> str:
>     cached = self._cache.get(url)
>     if cached is not None:
>         return cached
>     try:
>         body = self._fetch(url)
>         self._cache.put(url, body)
>         return body
>     except Exception:
>         raise
> ```
> This satisfies both tests (single fetch on repeat; and for the fallback test the first call populates cache, the second returns it). Use this version.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/crawl/test_fetcher.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/crawl/ tests/crawl/
git commit -m "feat: cached fetcher with offline replay"
```

---

### Task 2: Live BenchmarkSource (Roblox ecosystem)

**Files:**
- Create: `src/gaa/sources/roblox_benchmark.py`
- Test: `tests/sources/test_roblox_benchmark.py`

> The parser targets a JSON payload of CCU/visits points. **Confirm the real RoMonitor/Rolimon's endpoint + JSON shape at build time** and adjust `_parse` accordingly; the injected `fetch` keeps tests deterministic.

- [ ] **Step 1: Write the failing test**

`tests/sources/test_roblox_benchmark.py`:
```python
import json
from gaa.sources.roblox_benchmark import RoMonitorBenchmark

CANNED = json.dumps({"points": [
    {"date": "2026-05-01", "ccu": 5000},
    {"date": "2026-05-02", "ccu": 4900},
    {"date": "2026-05-03", "ccu": 4800}]})

def test_genre_trend_indexes_to_100(tmp_path):
    src = RoMonitorBenchmark(cache_dir=str(tmp_path), fetch_fn=lambda url: CANNED,
                             genre_url_tmpl="http://romon/{genre}.json")
    trend = src.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert trend["2026-05-01"] == 100.0
    assert round(trend["2026-05-03"], 1) == 96.0  # 4800/5000*100

def test_empty_payload_returns_empty(tmp_path):
    src = RoMonitorBenchmark(cache_dir=str(tmp_path), fetch_fn=lambda url: '{"points": []}',
                             genre_url_tmpl="http://romon/{genre}.json")
    assert src.genre_trend("survival", "2026-05-01", "2026-05-03") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_roblox_benchmark.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/sources/roblox_benchmark.py`:
```python
import json
from typing import Callable, Optional
from gaa.crawl.fetcher import CachedFetcher


class RoMonitorBenchmark:
    """BenchmarkSource backed by public Roblox ecosystem CCU data."""
    def __init__(self, cache_dir: str, genre_url_tmpl: str,
                 fetch_fn: Optional[Callable[[str], str]] = None) -> None:
        self._fetcher = CachedFetcher(cache_dir, fetch_fn)
        self._tmpl = genre_url_tmpl

    def _parse(self, body: str) -> dict[str, float]:
        data = json.loads(body)
        return {p["date"]: float(p["ccu"]) for p in data.get("points", [])}

    def genre_trend(self, genre: str, start: str, end: str) -> dict[str, float]:
        body = self._fetcher.get(self._tmpl.format(genre=genre))
        raw = {d: v for d, v in self._parse(body).items() if start <= d <= end}
        if len(raw) < 2:
            return {}
        base = raw[min(raw)]
        return {d: (v / base) * 100.0 for d, v in raw.items()} if base else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/sources/test_roblox_benchmark.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sources/roblox_benchmark.py tests/sources/test_roblox_benchmark.py
git commit -m "feat: live RoMonitor benchmark source (indexed genre trend)"
```

---

### Task 3: Live SignalsSource (events/news/social)

**Files:**
- Create: `src/gaa/sources/web_signals.py`
- Test: `tests/sources/test_web_signals.py`

> Confirm the real news/Reddit/Roblox-updates endpoints at build time; `_parse` here expects a JSON list of items and is the seam to adjust.

- [ ] **Step 1: Write the failing test**

`tests/sources/test_web_signals.py`:
```python
import json
from gaa.sources.web_signals import WebSignalsSource

CANNED = json.dumps([
    {"date": "2026-05-04", "title": "v3.2 update", "kind": "patch",
     "url": "http://p", "sentiment": -0.1},
    {"date": "2026-06-30", "title": "out of window", "kind": "news",
     "url": "http://n", "sentiment": 0.0}])

def test_events_filtered_to_window(tmp_path):
    src = WebSignalsSource(cache_dir=str(tmp_path), fetch_fn=lambda url: CANNED,
                           query_url_tmpl="http://news?q={game}")
    evs = src.events("MyGame", "survival", "2026-05-01", "2026-05-31")
    assert len(evs) == 1 and evs[0]["kind"] == "patch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sources/test_web_signals.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/sources/web_signals.py`:
```python
import json
from typing import Callable, Optional
from urllib.parse import quote
from gaa.crawl.fetcher import CachedFetcher


class WebSignalsSource:
    """SignalsSource backed by public news/social/update feeds."""
    def __init__(self, cache_dir: str, query_url_tmpl: str,
                 fetch_fn: Optional[Callable[[str], str]] = None) -> None:
        self._fetcher = CachedFetcher(cache_dir, fetch_fn)
        self._tmpl = query_url_tmpl

    def _parse(self, body: str) -> list[dict]:
        return json.loads(body)

    def events(self, game: str, genre: str, start: str, end: str) -> list[dict]:
        body = self._fetcher.get(self._tmpl.format(game=quote(game)))
        return [e for e in self._parse(body) if start <= e["date"] <= end]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/sources/test_web_signals.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/sources/web_signals.py tests/sources/test_web_signals.py
git commit -m "feat: live web signals source (window-filtered events)"
```

---

### Task 4: Profiler (LLM column-mapping proposal)

**Files:**
- Create: `src/gaa/onboarding/__init__.py` (empty)
- Create: `src/gaa/onboarding/profiler.py`
- Test: `tests/onboarding/test_profiler.py`
- Create: `tests/onboarding/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/onboarding/test_profiler.py`:
```python
import pandas as pd
from gaa.onboarding.profiler import Profiler
from gaa.llm.client import FakeLLM
from gaa.schema.profile import ColumnMapping

def test_propose_mapping_from_sample():
    sample = pd.DataFrame({"dt": ["2026-05-01"], "dau_count": [100],
                           "rev": [50.0], "country": ["SEA"]})
    preset = {"date_col": "dt",
              "metric_cols": {"dau_count": "dau", "rev": "revenue"},
              "dim_cols": {"country": "region"}}
    m = Profiler(FakeLLM(preset)).propose(sample)
    assert isinstance(m, ColumnMapping)
    assert m.date_col == "dt"
    assert m.metric_cols["rev"] == "revenue"

def test_confirmation_message_lists_mapping():
    sample = pd.DataFrame({"dt": ["2026-05-01"], "dau_count": [100]})
    m = ColumnMapping(date_col="dt", metric_cols={"dau_count": "dau"}, dim_cols={})
    msg = Profiler(FakeLLM({})).confirmation_message(m)
    assert "dt" in msg and "dau" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/onboarding/test_profiler.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/onboarding/profiler.py`:
```python
import pandas as pd
from gaa.llm.client import LLM
from gaa.schema.profile import ColumnMapping

SYSTEM = (
    "Map a game-metrics table to a canonical schema. Canonical metric names include: "
    "dau, mau, revenue, arppu, retention_d1, retention_d7, retention_d30, sessions, playtime. "
    "Canonical dimensions: platform, region, version, cohort, device, source. "
    "Return JSON: {date_col, metric_cols:{source_col->canonical_metric}, "
    "dim_cols:{source_col->canonical_dim}}. Only include columns you are confident about."
)


class Profiler:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def propose(self, sample: pd.DataFrame) -> ColumnMapping:
        cols = list(sample.columns)
        head = sample.head(5).astype(str).to_dict(orient="records")
        user = f"COLUMNS: {cols}\nSAMPLE ROWS: {head}"
        raw = self._llm.complete_json(SYSTEM, user)
        return ColumnMapping(**raw)

    def confirmation_message(self, mapping: ColumnMapping) -> str:
        metrics = ", ".join(f"{s} → {c}" for s, c in mapping.metric_cols.items())
        dims = ", ".join(f"{s} → {c}" for s, c in mapping.dim_cols.items()) or "(none)"
        return (f"I read your data as:\n• date = `{mapping.date_col}`\n"
                f"• metrics: {metrics}\n• dimensions: {dims}\n"
                f"Reply 'confirm' to save, or tell me what to fix.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/onboarding/test_profiler.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/onboarding/ tests/onboarding/
git commit -m "feat: LLM profiler (propose column mapping + confirmation message)"
```

---

### Task 5: Onboarding endpoints (propose → confirm → ingest)

**Files:**
- Modify: `src/gaa/api/app.py` (add `/onboard/propose`, `/onboard/confirm`)
- Test: `tests/api/test_onboarding.py`

`/onboard/propose` reads a CSV (path), returns the proposed mapping + a confirmation message. `/onboard/confirm` takes the (possibly edited) mapping + game meta, ingests via the right adapter into `MetricsStore`, and saves the `GameProfile`.

- [ ] **Step 1: Write the failing test**

`tests/api/test_onboarding.py`:
```python
from fastapi.testclient import TestClient
from gaa.api.app import create_app
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.llm.client import FakeLLM

def _app(tmp_path):
    return create_app(
        profile_store=ProfileStore(str(tmp_path / "p.sqlite")),
        metrics_store=MetricsStore(str(tmp_path / "m")),
        llm=FakeLLM({"date_col": "Date", "metric_cols": {"DAU": "dau"},
                     "dim_cols": {"Country": "region"}}))

def test_propose_returns_mapping_and_message(tmp_path):
    c = TestClient(_app(tmp_path))
    r = c.post("/onboard/propose",
               json={"adapter": "csv", "csv_path": "src/gaa/data/sample/roblox_export.csv"})
    assert r.status_code == 200
    assert r.json()["mapping"]["date_col"] == "Date"
    assert "confirm" in r.json()["message"].lower()

def test_confirm_ingests_and_saves_profile(tmp_path):
    c = TestClient(_app(tmp_path))
    body = {"name": "MyGame", "platform": "roblox", "genre": "survival",
            "adapter": "csv", "csv_path": "src/gaa/data/sample/roblox_export.csv",
            "mapping": {"date_col": "Date", "metric_cols": {"DAU": "dau"},
                        "dim_cols": {"Country": "region"}}}
    r = c.post("/onboard/confirm", json=body)
    assert r.status_code == 201
    assert r.json()["row_count"] == 6  # 6 rows x 1 metric
    assert "MyGame" in c.get("/profiles").json()["names"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_onboarding.py -v`
Expected: FAIL (routes not found → 404).

- [ ] **Step 3: Add routes to `src/gaa/api/app.py`**

Add request models near the others:
```python
class OnboardProposeRequest(BaseModel):
    adapter: str            # "csv" | "roblox"
    csv_path: str

class OnboardConfirmRequest(BaseModel):
    name: str
    platform: str
    genre: str
    adapter: str
    csv_path: str
    mapping: ColumnMapping
    external_source_config: dict = {}
```

Inside `create_app`, after the engine wiring, add a `Profiler` and the routes:
```python
    from gaa.onboarding.profiler import Profiler
    import pandas as pd
    profiler = Profiler(llm or LLMClient(settings))

    def _load_canonical(adapter: str, csv_path: str, mapping: ColumnMapping):
        if adapter == "roblox":
            return RobloxAdapter().load(csv_path, mapping)
        if adapter == "csv":
            return CSVAdapter().load(csv_path, mapping)
        raise HTTPException(400, f"unknown adapter '{adapter}'")

    @app.post("/onboard/propose")
    def onboard_propose(req: OnboardProposeRequest):
        sample = pd.read_csv(req.csv_path).head(20)
        mapping = profiler.propose(sample)
        return {"mapping": mapping.model_dump(),
                "message": profiler.confirmation_message(mapping)}

    @app.post("/onboard/confirm", status_code=201)
    def onboard_confirm(req: OnboardConfirmRequest):
        df = _load_canonical(req.adapter, req.csv_path, req.mapping)
        metrics.save(req.name, df)
        profile = GameProfile(name=req.name, platform=req.platform, genre=req.genre,
                              mapping=req.mapping,
                              external_source_config=req.external_source_config)
        store.save(profile)
        store.set_active(req.name)
        return {"name": req.name, "row_count": int(len(df)),
                "metrics": sorted(df["metric"].unique().tolist())}
```

> The `engine` for analysis is built from injected `benchmark`/`signals`; the profiler reuses the injected `llm`. Ensure `metrics` (MetricsStore) and `store` (ProfileStore) are the same instances used elsewhere in `create_app`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_onboarding.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/api/app.py tests/api/test_onboarding.py
git commit -m "feat: chat-assisted onboarding endpoints (propose/confirm/ingest)"
```

---

### Task 6: Plotly charts

**Files:**
- Create: `src/gaa/render/charts.py`
- Test: `tests/render/test_charts.py`
- Create: `tests/render/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/render/test_charts.py`:
```python
import pandas as pd
import plotly.graph_objects as go
from gaa.render.charts import (
    timeseries_fig, overlay_fig, confidence_matrix_fig)
from gaa.schema.hypothesis import AttributionHypothesis, Cause, Causes
from gaa.schema.confidence import Confidence

def test_timeseries_fig_has_trace():
    s = pd.Series([100.0, 90.0, 60.0],
                  index=pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]))
    fig = timeseries_fig(s, "dau", "2026-05-01", "2026-05-03")
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1

def test_overlay_indexes_both_series():
    game = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    genre = {"2026-05-01": 100.0, "2026-05-03": 98.0}
    fig = overlay_fig(game, genre, "dau")
    assert len(fig.data) == 2  # game + genre

def test_confidence_matrix_plots_each_claim():
    h = AttributionHypothesis(
        main_story="x", confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="a", evidence_ids=["L1"], likelihood="Likely",
                                       evidence_quality="Strong")]))
    fig = confidence_matrix_fig(h)
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/render/test_charts.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/gaa/render/charts.py`:
```python
import pandas as pd
import plotly.graph_objects as go

_LK = {"Unlikely": 1, "Possible": 2, "Likely": 3, "Very likely": 4}
_EQ = {"Weak": 1, "Moderate": 2, "Strong": 3}


def timeseries_fig(series: pd.Series, metric: str, start: str, end: str) -> go.Figure:
    fig = go.Figure(go.Scatter(x=list(series.index), y=list(series.values),
                               mode="lines+markers", name=metric))
    fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(title=f"{metric} over time", template="plotly_white")
    return fig


def overlay_fig(game: pd.Series, genre: dict[str, float], metric: str) -> go.Figure:
    g = game.sort_index()
    base = g.iloc[0] if len(g) and g.iloc[0] else 1.0
    game_idx = (g / base) * 100.0
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[str(d.date()) for d in game_idx.index],
                             y=list(game_idx.values), mode="lines+markers",
                             name=f"Your {metric} (indexed)"))
    if genre:
        ks = sorted(genre)
        fig.add_trace(go.Scatter(x=ks, y=[genre[k] for k in ks],
                                 mode="lines+markers", name="Genre (indexed)"))
    fig.update_layout(title="You vs the market (indexed to 100)", template="plotly_white")
    return fig


def confidence_matrix_fig(h) -> go.Figure:
    xs, ys, labels = [], [], []
    items = ([(c.claim, c) for c in h.causes.internal]
             + [(c.claim, c) for c in h.causes.market]
             + [(s.description, s) for s in h.scenarios])
    for label, it in items:
        xs.append(_EQ.get(it.evidence_quality, 1))
        ys.append(_LK.get(it.likelihood, 2))
        labels.append(label[:40])
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="markers+text", text=labels,
                               textposition="top center", marker={"size": 14}))
    fig.update_layout(title="Confidence matrix (likelihood × evidence)",
                      xaxis={"tickvals": [1, 2, 3], "ticktext": ["Weak", "Moderate", "Strong"],
                             "title": "Evidence quality", "range": [0.5, 3.5]},
                      yaxis={"tickvals": [1, 2, 3, 4],
                             "ticktext": ["Unlikely", "Possible", "Likely", "Very likely"],
                             "title": "Likelihood", "range": [0.5, 4.5]},
                      template="plotly_white")
    return fig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/render/test_charts.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/render/charts.py tests/render/
git commit -m "feat: plotly charts (timeseries, internal-vs-market overlay, confidence matrix)"
```

---

### Task 7: HTML report renderer (self-contained, inline Plotly)

**Files:**
- Create: `src/gaa/render/templates/report.html.j2`
- Create: `src/gaa/render/report.py`
- Test: `tests/render/test_report.py`

- [ ] **Step 1: Write the failing test**

`tests/render/test_report.py`:
```python
import pandas as pd
from gaa.render.report import render_report
from gaa.schema.hypothesis import AttributionHypothesis, Cause, Causes
from gaa.schema.confidence import Confidence

def _hyp():
    return AttributionHypothesis(
        main_story="Mostly internal — SEA fell.",
        confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="SEA collapse", evidence_ids=["L1"],
                                       likelihood="Likely", evidence_quality="Strong")]),
        assumptions_and_gaps=["no UA data"])

def test_report_is_self_contained_html():
    series = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    html = render_report(_hyp(), metric="dau", start="2026-05-01", end="2026-05-03",
                         series=series, genre_trend={"2026-05-01": 100.0, "2026-05-03": 98.0})
    assert "<html" in html.lower()
    assert "Mostly internal" in html
    assert "Plotly" in html          # inline plotly.js present
    assert "no UA data" in html      # gaps shown
    assert "Confidence matrix" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/render/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the Jinja2 template `src/gaa/render/templates/report.html.j2`**

```html
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{{ h.main_story }}</title>
<script>{{ plotlyjs|safe }}</script>
<style>
 body{font-family:system-ui,Arial;margin:24px;color:#1a1a1a;max-width:1000px}
 .headline{font-size:1.4em;font-weight:700;margin:8px 0}
 .badge{display:inline-block;padding:2px 8px;border-radius:10px;background:#eef;margin-left:6px}
 .internal{color:#1565c0}.market{color:#e07b00}
 .cite{color:#888;font-size:.85em}.gaps{background:#fff8e1;padding:10px;border-radius:8px}
 .chart{margin:18px 0}
</style></head><body>
 <div class="headline">{{ h.main_story }}
   <span class="badge">{{ h.confidence.likelihood }} · {{ h.confidence.evidence_quality }} evidence</span></div>
 <div class="chart">{{ charts.timeseries|safe }}</div>
 <div class="chart">{{ charts.overlay|safe }}</div>
 <h3>Causes</h3>
 {% for c in h.causes.internal %}<p class="internal">🔵 {{ c.claim }}
   <span class="badge">{{ c.likelihood }} · {{ c.evidence_quality }}</span>
   <span class="cite">{{ c.evidence_ids|join(', ') }}</span></p>{% endfor %}
 {% for c in h.causes.market %}<p class="market">🟠 {{ c.claim }}
   <span class="badge">{{ c.likelihood }} · {{ c.evidence_quality }}</span>
   <span class="cite">{{ c.evidence_ids|join(', ') }}</span></p>{% endfor %}
 <div class="chart">{{ charts.matrix|safe }}</div>
 {% if h.scenarios %}<h3>Next scenarios</h3>
 {% for s in h.scenarios %}<p>• {{ s.description }}
   <span class="badge">{{ s.likelihood }} · {{ s.evidence_quality }}</span>
   {% if s.signals_to_watch %}<br><span class="cite">watch: {{ s.signals_to_watch|join('; ') }}</span>{% endif %}</p>{% endfor %}{% endif %}
 {% if h.risks %}<h3>Risks</h3>{% for r in h.risks %}<p>⚠ {{ r.description }}
   <span class="badge">{{ r.likelihood }} · {{ r.evidence_quality }}</span></p>{% endfor %}{% endif %}
 {% if h.assumptions_and_gaps %}<div class="gaps"><b>Assumptions &amp; gaps:</b>
   <ul>{% for g in h.assumptions_and_gaps %}<li>{{ g }}</li>{% endfor %}</ul></div>{% endif %}
 <h3>Evidence</h3>
 <ul class="cite">{% for e in h.evidence %}<li>{{ e.id }} [{{ e.source_type }}/{{ e.strength }}]
   {{ e.claim }} ({{ e.value }}) — {{ e.source }}</li>{% endfor %}</ul>
 <p class="cite">Generated by an AI agent. Scenarios, not decisions — the human decides.</p>
</body></html>
```

- [ ] **Step 4: Write `src/gaa/render/report.py`**

```python
import os
import pandas as pd
import plotly.io as pio
import plotly.offline as pyo
from jinja2 import Environment, FileSystemLoader, select_autoescape
from gaa.schema.hypothesis import AttributionHypothesis
from gaa.render.charts import timeseries_fig, overlay_fig, confidence_matrix_fig

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES),
                   autoescape=select_autoescape(["html"]))


def _div(fig) -> str:
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       default_width="100%", default_height="380px")


def render_report(h: AttributionHypothesis, metric: str, start: str, end: str,
                  series: pd.Series, genre_trend: dict[str, float]) -> str:
    charts = {
        "timeseries": _div(timeseries_fig(series, metric, start, end)),
        "overlay": _div(overlay_fig(series, genre_trend, metric)),
        "matrix": _div(confidence_matrix_fig(h)),
    }
    return _env.get_template("report.html.j2").render(
        h=h, charts=charts, plotlyjs=pyo.get_plotlyjs())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/render/test_report.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/render/templates/report.html.j2 src/gaa/render/report.py tests/render/test_report.py
git commit -m "feat: self-contained HTML report renderer (inline plotly)"
```

> **Note — trace panel ("How this was computed"), optional demo polish.** The hypothesis carries the per-run reasoning trace from **[Plan 2 · Task 15](2026-06-10-game-attribution-agent-plan-2-analysis-engine.md)** at `h.trace` (a `RunTrace` with ordered `events`). Rendering it makes the agent *show its work* — which module fired, what it found, where data was thin — the relatability win that sells the demo to voters. **No `render_report` change is needed** (`h` is already in template scope; `h.trace` rides through `model_dump()` to `/analyze` too). Drop this block into `report.html.j2` just before the closing footer `<p class="cite">…</p>`, guarded so older/snapshot hypotheses with no trace still render:
>
> ```html
>  {% if h.trace %}
>  <h3>How this was computed</h3>
>  <ol class="cite">
>  {% for ev in h.trace.events %}
>    <li>{{ ev.module }} — <span class="badge">{{ ev.status }}</span>
>        {{ ev.entries_added }} finding(s){% if ev.ledger_ids %} ({{ ev.ledger_ids|join(', ') }}){% endif %}
>        <span class="cite">{{ '%.0f'|format(ev.elapsed_ms) }} ms</span>
>        {% if ev.note %}<br><span class="cite">{{ ev.note }}</span>{% endif %}</li>
>  {% endfor %}
>  </ol>{% endif %}
> ```
>
> To lock it under test, attach a `RunTrace` to `_hyp()` in `tests/render/test_report.py` (`from gaa.schema.trace import RunTrace, TraceEvent`) and add `assert "How this was computed" in html`. Optional CSS: color the status badge (`data_gap`→amber, `error`→red) reusing the existing `.gaps` palette.

---

### Task 8: Wire the HTML report into `/analyze`

**Files:**
- Modify: `src/gaa/engine.py` (add `analyze_full` returning resolved metric/window)
- Modify: `src/gaa/api/app.py` (`/analyze` returns rendered html)
- Test: `tests/test_engine_full.py`
- Test: `tests/api/test_analyze_html.py`

- [ ] **Step 1: Write the failing engine test**

`tests/test_engine_full.py`:
```python
import pandas as pd
from gaa.engine import AttributionEngine, AnalysisResult
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping

def _profile():
    return GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={}))

def _metrics():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    return df

def test_analyze_full_resolves_metric_and_window():
    engine = AttributionEngine(FakeLLM({"main_story": "x",
        "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
        "assumptions_and_gaps": []}),
        FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
        FixtureSignalsSource([]))
    res = engine.analyze_full(_profile(), _metrics(), "what happened?")
    assert isinstance(res, AnalysisResult)
    assert res.metric == "dau"
    assert res.start == "2026-05-01" and res.end == "2026-05-03"
    assert res.hypothesis.main_story == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_engine_full.py -v`
Expected: FAIL (`AnalysisResult` / `analyze_full` not defined).

- [ ] **Step 3: Refactor `src/gaa/engine.py`**

Add the dataclass and method; refactor the run into a shared helper:
```python
from dataclasses import dataclass

@dataclass
class AnalysisResult:
    hypothesis: AttributionHypothesis
    metric: str | None
    start: str | None
    end: str | None
```
Replace `analyze` with a shared `_run` that returns `(hypothesis, ctx)`:
```python
    def _run(self, profile, metrics, query):
        parsed = parse_query(query)
        ctx = AnalysisContext(profile=profile, metrics=metrics, query=query,
                              metric=parsed["metric"], direction=parsed["direction"])
        ledger = EvidenceLedger()
        AnomalyDetection().run(ctx, ledger)
        SegmentDecomposition().run(ctx, ledger)
        MarketBenchmark(self._benchmark).run(ctx, ledger)
        CompetitorSignals(self._signals).run(ctx, ledger)
        hyp = validate_citations(self._synth.synthesize(ledger, query), ledger)
        return hyp, ctx

    def analyze(self, profile, metrics, query):
        return self._run(profile, metrics, query)[0]

    def analyze_full(self, profile, metrics, query):
        hyp, ctx = self._run(profile, metrics, query)
        return AnalysisResult(hypothesis=hyp, metric=ctx.metric,
                              start=ctx.start, end=ctx.end)
```

> Keep `self._benchmark`/`self._signals` as set in `__init__`. The existing Plan 2 `test_engine.py` still passes because `analyze` keeps its signature + return type.

- [ ] **Step 4: Write the failing API test**

`tests/api/test_analyze_html.py`:
```python
import pandas as pd
from fastapi.testclient import TestClient
from gaa.api.app import create_app
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource

def test_analyze_returns_rendered_html(tmp_path):
    ps = ProfileStore(str(tmp_path / "p.sqlite"))
    ps.save(GameProfile(name="MyGame", platform="roblox", genre="survival",
                        mapping=ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={})))
    ps.set_active("MyGame")
    ms = MetricsStore(str(tmp_path / "m"))
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    ms.save("MyGame", df)
    app = create_app(profile_store=ps, metrics_store=ms,
                     llm=FakeLLM({"main_story": "Mostly internal.",
                                  "causes": {"internal": [], "market": []},
                                  "scenarios": [], "risks": [], "assumptions_and_gaps": []}),
                     benchmark=FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
                     signals=FixtureSignalsSource([]))
    r = TestClient(app).post("/analyze", json={"query": "why did dau drop?"})
    assert r.status_code == 200
    body = r.json()
    assert "<html" in body["html"].lower()
    assert "Mostly internal." in body["html"]
```

- [ ] **Step 5: Update `/analyze` in `src/gaa/api/app.py`**

Inject a benchmark ref into `create_app` scope (it already is) and render:
```python
    from gaa.render.report import render_report

    @app.post("/analyze")
    def analyze(req: AnalyzeRequest):
        profile = store.get(req.game) if req.game else store.get_active()
        if profile is None:
            raise HTTPException(400, "no active GameProfile; create one via /profiles")
        try:
            df = metrics.load(profile.name)
        except FileNotFoundError:
            raise HTTPException(400, f"no metrics ingested for '{profile.name}'")
        res = engine.analyze_full(profile, df, req.query)
        series = (df[df["metric"] == res.metric].groupby("date")["value"].sum().sort_index()
                  if res.metric else df.groupby("date")["value"].sum())
        genre_trend = (benchmark_ref.genre_trend(profile.genre, res.start, res.end)
                       if res.start and res.end else {})
        html = render_report(res.hypothesis, metric=res.metric or "metric",
                             start=res.start or "", end=res.end or "",
                             series=series, genre_trend=genre_trend)
        return {"hypothesis": res.hypothesis.model_dump(),
                "markdown_summary": to_markdown(res.hypothesis), "html": html}
```
Where `benchmark_ref` is the benchmark instance built in `create_app` (assign it to a local var `benchmark_ref = benchmark or FixtureBenchmarkSource({})` before constructing the engine, and pass the same instance to the engine).

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_engine.py tests/test_engine_full.py tests/api/ -v`
Expected: PASS (Plan 2 engine test still green; new html test green).

- [ ] **Step 7: Commit**

```bash
git add src/gaa/engine.py src/gaa/api/app.py tests/test_engine_full.py tests/api/test_analyze_html.py
git commit -m "feat: render full HTML report in /analyze"
```

---

### Task 9: `/chat` router (setup vs analysis) for the AgentBase chat UX

**Files:**
- Create: `src/gaa/orchestrator/router.py`
- Modify: `src/gaa/api/app.py` (add `/chat`)
- Test: `tests/orchestrator/test_router.py`
- Test: `tests/api/test_chat.py`

- [ ] **Step 1: Write the failing router test**

`tests/orchestrator/test_router.py`:
```python
from gaa.orchestrator.router import classify_intent

def test_setup_intent():
    assert classify_intent("connect my data", has_active_profile=False) == "setup"
    assert classify_intent("here is my CSV to onboard", has_active_profile=True) == "setup"

def test_analysis_intent():
    assert classify_intent("why did revenue drop?", has_active_profile=True) == "analyze"

def test_defaults_to_setup_without_profile():
    assert classify_intent("what's going on?", has_active_profile=False) == "setup"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/test_router.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/gaa/orchestrator/router.py`**

```python
_SETUP_HINTS = ("connect", "onboard", "upload", "set up", "setup", "add my data", "csv", "import")


def classify_intent(message: str, has_active_profile: bool) -> str:
    m = message.lower()
    if any(h in m for h in _SETUP_HINTS):
        return "setup"
    if not has_active_profile:
        return "setup"   # nothing to analyze yet
    return "analyze"
```

- [ ] **Step 4: Write the failing API test**

`tests/api/test_chat.py`:
```python
from fastapi.testclient import TestClient
from gaa.api.app import create_app
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.llm.client import FakeLLM

def test_chat_routes_to_setup_when_no_profile(tmp_path):
    app = create_app(profile_store=ProfileStore(str(tmp_path / "p.sqlite")),
                     metrics_store=MetricsStore(str(tmp_path / "m")),
                     llm=FakeLLM({}))
    r = TestClient(app).post("/chat", json={"message": "hello"})
    assert r.status_code == 200 and r.json()["mode"] == "setup"
```

- [ ] **Step 5: Add `/chat` to `src/gaa/api/app.py`**

```python
class ChatRequest(BaseModel):
    message: str

    # in create_app:
    from gaa.orchestrator.router import classify_intent

    @app.post("/chat")
    def chat(req: ChatRequest):
        mode = classify_intent(req.message, has_active_profile=store.get_active() is not None)
        if mode == "setup":
            return {"mode": "setup",
                    "message": "Let's connect your data. POST your CSV path to "
                               "/onboard/propose, then /onboard/confirm."}
        result = analyze(AnalyzeRequest(query=req.message))  # reuse the analyze handler
        return {"mode": "analyze", **result}
```

> `analyze` is the function defined for the `/analyze` route inside `create_app`; calling it directly reuses its logic. Ensure `AnalyzeRequest` is importable in scope (it is, defined at module top).

- [ ] **Step 6: Run tests**

Run: `pytest tests/orchestrator/test_router.py tests/api/test_chat.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add src/gaa/orchestrator/router.py src/gaa/api/app.py tests/orchestrator/test_router.py tests/api/test_chat.py
git commit -m "feat: /chat router (setup vs analysis intent)"
```

---

### Task 10: Production wiring, demo snapshot, README & form

**Files:**
- Modify: `src/gaa/api/app.py` (default to live sources in production)
- Create: `src/gaa/data/snapshots/hero.json`
- Modify: `src/gaa/api/app.py` (add `GET /demo`)
- Test: `tests/api/test_demo.py`
- Modify: `README.md`
- Create: `docs/demo-script.md`
- Create: `docs/submission-form.md`

- [ ] **Step 1: Default `create_app` to live sources when none injected**

In `create_app`, replace the fixture defaults with live sources built from `Settings`:
```python
    from gaa.sources.roblox_benchmark import RoMonitorBenchmark
    from gaa.sources.web_signals import WebSignalsSource
    benchmark_ref = benchmark or RoMonitorBenchmark(
        cache_dir=settings.cache_dir + "/benchmark",
        genre_url_tmpl=os.environ.get("GAA_BENCHMARK_URL_TMPL", "http://example/{genre}.json"))
    signals_ref = signals or WebSignalsSource(
        cache_dir=settings.cache_dir + "/signals",
        query_url_tmpl=os.environ.get("GAA_SIGNALS_URL_TMPL", "http://example/news?q={game}"))
    engine = AttributionEngine(llm=llm or LLMClient(settings),
                               benchmark=benchmark_ref, signals=signals_ref)
```
(Add `import os` at top if not present.) Tests still inject fixtures, so they stay offline.

- [ ] **Step 2: Create a pre-baked hero snapshot**

Generate it once from a real run, then save the response JSON to `src/gaa/data/snapshots/hero.json` (keys: `hypothesis`, `markdown_summary`, `html`). For the first commit, hand-author a minimal valid file:
```json
{"hypothesis": {"main_story": "Demo snapshot — replace with a real run.",
  "confidence": {"likelihood": "Likely", "evidence_quality": "Moderate"},
  "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
  "evidence": [], "assumptions_and_gaps": []},
 "markdown_summary": "Demo snapshot.", "html": "<html><body>Demo snapshot</body></html>"}
```

- [ ] **Step 3: Write the failing demo test**

`tests/api/test_demo.py`:
```python
from fastapi.testclient import TestClient
from gaa.api.app import create_app
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.llm.client import FakeLLM

def test_demo_endpoint_serves_snapshot(tmp_path):
    app = create_app(profile_store=ProfileStore(str(tmp_path / "p.sqlite")),
                     metrics_store=MetricsStore(str(tmp_path / "m")), llm=FakeLLM({}))
    r = TestClient(app).get("/demo")
    assert r.status_code == 200
    assert "html" in r.json() and "<html" in r.json()["html"].lower()
```

- [ ] **Step 4: Add `GET /demo` to `src/gaa/api/app.py`**

```python
    import json as _json
    from pathlib import Path as _Path

    @app.get("/demo")
    def demo():
        snap = _Path(__file__).resolve().parents[1] / "data" / "snapshots" / "hero.json"
        return _json.loads(snap.read_text(encoding="utf-8"))
```

- [ ] **Step 5: Run the demo test + full suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 6: Write `README.md`** (overwrite Plan 1 stub with the full version)

```markdown
# Game Attribution Agent — GreenNode Claw-a-thon 2026 (Data Analysis track)

An AI agent that reconstructs the story behind a game's metric movement, separating
**internal** causes from **market-wide** ones, with **dual-axis confidence** (likelihood +
evidence quality) and **cited evidence**. It presents scenarios, never decisions.

## What it does
- Connect any game's data via chat (CSV or Roblox export) — no code.
- Ask "what happened to my game?" → it discovers the notable movement, runs 4 analysis
  modules (anomaly, segment, market benchmark, competitor/event signals), and returns an
  interactive HTML report with charts + a confidence matrix.

## Run locally
    pip install -r requirements.txt && pip install -e .
    uvicorn gaa.api.app:app --port 8080
    curl localhost:8080/health

## Key endpoints
- `POST /chat` — single entry; routes setup vs analysis.
- `POST /onboard/propose` + `POST /onboard/confirm` — chat-assisted data setup.
- `POST /analyze` — `{html, hypothesis, markdown_summary}`.
- `GET /demo` — pre-baked hero report (demo fallback).

## Models
Uses Anthropic Claude (declared per rules) for orchestration + synthesis, with MaaS
(Gemma/Qwen) fallback via `GAA_MAAS_BASE_URL`. Set `ANTHROPIC_API_KEY`.

## Data
External/market data is public (Roblox ecosystem); internal game data is aggregate and
PII-stripped. No customer/confidential data is used.

## Deployment
See the "Deployment" section for the exact AgentBase steps used.
```

- [ ] **Step 7: Write `docs/demo-script.md`** (2–3 min, 2-act)

```markdown
# Demo script (2–3 min)

ACT 1 — "any team, no code" (0:00–1:00)
- POST /onboard/propose with a CSV → show the agent's proposed mapping + confirmation msg.
- POST /onboard/confirm → "Saved MyGame, ingested N rows."
- (Optional) repeat with a non-Roblox CSV to show platform-agnostic setup.

ACT 2 — the payoff (1:00–2:30)
- POST /chat {"message": "what's going on with my game?"}
- Open the returned HTML report: headline + dual-confidence badge; time-series with the
  movement shaded; internal-vs-market overlay ("is it us or the market?"); confidence matrix;
  honest assumptions/gaps line.
- Close on the principle: "Scenarios, not decisions — the human decides."

Fallback: if live data is slow, demo GET /demo (pre-baked hero report).
```

- [ ] **Step 8: Write `docs/submission-form.md`** (≤300-char summary + checklist)

```markdown
# Submission

Form summary (<=300 chars):
"Game Attribution Agent: ask 'why did my game's metric move?' It separates internal vs
market causes, gives 2 confidence scores (likelihood + evidence) with citations, and returns
an interactive chart report. Connect any game's data via chat — no code."

Checklist:
- [ ] Agent running on AgentBase, judges can call (GET /health, POST /chat).
- [ ] Demo video 2–3 min on YouTube/OneDrive (use docs/demo-script.md).
- [ ] README + this form complete, no placeholders.
- [ ] External model (Claude) declared in README.
- [ ] Team names + @vng.com.vn emails.
```

- [ ] **Step 9: Commit**

```bash
git add src/gaa/api/app.py src/gaa/data/snapshots/hero.json tests/api/test_demo.py README.md docs/demo-script.md docs/submission-form.md
git commit -m "feat: live-source wiring, demo snapshot, README + submission docs"
```

- [ ] **Step 10: Re-deploy to AgentBase and verify end-to-end**

Rebuild the image and deploy (per Plan 1 Task 9). Verify:
```bash
curl -s <agentbase-endpoint>/health
curl -s -X POST <agentbase-endpoint>/chat -H 'content-type: application/json' -d '{"message":"hello"}'
curl -s <agentbase-endpoint>/demo | python -c "import sys,json;print('html' in json.load(sys.stdin))"
```
Expected: health ok; chat returns a setup message; demo returns the snapshot. Record the live `GAA_BENCHMARK_URL_TMPL` / `GAA_SIGNALS_URL_TMPL` values in the README.

---

## Self-Review (completed during authoring)

**Spec coverage (Plan 3 portion):**
- Crawler + cache (offline replay) → Task 1 ✓
- Live external sources behind Plan 2 interfaces → Tasks 2, 3 ✓
- Chat-assisted onboarding (propose → confirm → ingest) → Tasks 4, 5 ✓
- 4 charts incl. internal-vs-market overlay + dual-confidence matrix → Task 6 ✓
- Self-contained HTML report (inline Plotly) → Task 7 ✓
- Reasoning-trace panel ("How this was computed", surfaces Plan 2 Task 15's `hypothesis.trace`) → Task 7 note (optional polish) ✓
- `/analyze` returns real `html` → Task 8 ✓
- `/chat` router (setup vs analysis) → Task 9 ✓
- Reliability: cache replay (Task 1), LLM fallback (Plan 2 Task 10), pre-baked snapshot (Task 10) ✓
- README + external-model declaration + demo script + form summary → Task 10 ✓

**Placeholder scan:** No TBD/TODO. The live-endpoint URLs are env-configurable with explicit "confirm at build time" steps (Tasks 2, 3, 10) — a deliberate seam, not a gap. The hero snapshot ships minimal-but-valid and is replaced from a real run (Task 10 Step 2).

**Type consistency:** `BenchmarkSource.genre_trend(genre,start,end)->dict[str,float]` and `SignalsSource.events(game,genre,start,end)->list[dict]` match Plan 2 fixtures and modules exactly. `ColumnMapping(date_col, metric_cols, dim_cols)` consistent in profiler + onboarding + adapters. `render_report(h, metric, start, end, series, genre_trend)` signature matches its call in `/analyze`. `AnalysisResult(hypothesis, metric, start, end)` consistent between engine and API. `create_app(...)` injection params extend Plans 1 & 2 without breaking their tests (fixtures still injectable). `classify_intent(message, has_active_profile)` consistent across router test and `/chat`. The CachedFetcher `get` final form (cache-first) is fixed in Task 1's note to satisfy both fetcher tests.
```
