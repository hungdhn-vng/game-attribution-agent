# Game Attribution Agent — Plan 0: AgentBase + LangGraph Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **The GreenNode AgentBase skill toolkit is installed at `.claude/skills/` — invoke `/agentbase-llm` and `/agentbase-deploy` for platform operations (they hold the authoritative API URLs; never construct platform URLs from memory).**

**Goal:** Wrap the (framework-agnostic) `gaa` engine in a **LangGraph** graph served by the **GreenNode AgentBase SDK** (`GreenNodeAgentBaseApp`), using the **GreenNode AI Platform MaaS** (OpenAI-compatible) LLM, and deploy it to AgentBase Runtime.

**Why this plan exists:** Discovery of the AgentBase platform (skill repo `vngcloud/greennode-agentbase-skills`) changed the *shell*, not the *core*. The deterministic analysis pipeline + Evidence Ledger + dual confidence (Plans 1–3) are unchanged. This plan defines: the MaaS LLM client, the LangGraph state/nodes/graph, the `main.py` entrypoint, and the deploy procedure.

**Architecture:** `main.py` (SDK `@app.entrypoint`) → `GraphAgent.handle(payload, session_id, user_id)` → a compiled **LangGraph** `StateGraph`. The graph routes intent (setup vs analyze), runs our nodes, and persists multi-turn state via a checkpointer (AgentBase Memory in prod, `MemorySaver` locally). Our analysis modules / ledger / synthesizer / validator / renderer / profiler stay pure Python and are *called by* graph nodes — the LLM never invents findings.

**Tech Stack:** `greennode-agentbase`, `greennode-agent-bridge[langgraph]`, `langgraph>=1.0,<2`, `langchain-openai>=1.1,<2`, `python-dotenv`, plus Plan 1–3 deps (pandas, duckdb, pyarrow, plotly, jinja2, httpx, beautifulsoup4, pytest).

---

## Supersession map (read first)

This plan **replaces** these tasks from the earlier plans; do the rest of those plans as written:

| Earlier task | Status | Replaced by |
|---|---|---|
| Plan 1 · Task 0 (skeleton) | **superseded** | Plan 0 · Task 1 (AgentBase scaffold) — keep `src/gaa` layout + add root `main.py` |
| Plan 1 · Task 1 (config) | **amended** | Plan 0 · Task 2 (LLM_* env vars) |
| Plan 1 · Tasks 7–9 (FastAPI app, generic Dockerfile, generic deploy) | **superseded** | Plan 0 · Tasks 1, 7, 8 (SDK `main.py`, scaffold Dockerfile, `/agentbase-deploy`) |
| Plan 2 · Task 10 (anthropic LLM client) | **superseded** | Plan 0 · Task 3 (MaaS `ChatOpenAI` client) — `LLM` protocol + `FakeLLM` unchanged |
| Plan 2 · Task 13–14 (`/analyze` route, engine wiring) | **amended** | Engine library stays; graph (Plan 0 Task 4) calls `AttributionEngine`; no FastAPI route |
| Plan 3 · Tasks 5, 8, 9 (FastAPI `/onboard`, `/analyze` html, `/chat` routes) | **superseded** | Plan 0 · Tasks 4, 5 (graph nodes) — handlers (`Profiler`, `render_report`, `classify_intent`, `to_markdown`) reused verbatim |
| Plan 3 · Task 10 (FastAPI `/demo` + live wiring + README) | **amended** | Plan 0 · Tasks 8, 9 (deploy + README/snapshot) |

**Unchanged & still required:** Plan 1 Tasks 2–6 (canonical schema, ColumnMapping/GameProfile, CSV+Roblox adapters, ProfileStore); Plan 2 Tasks 1–9, 11–13 (hypothesis/ledger schema, confidence, MetricsStore, module base + 4 modules, source interfaces+fixtures, synthesizer, validator, planner+markdown); Plan 3 Tasks 1–4, 6, 7 (cached fetcher, live RoMonitor benchmark, live web signals, profiler, charts, HTML report). The pure-logic `AttributionEngine` (Plan 2 Task 14 `gaa/engine.py`) stays as a **library** the graph calls.

---

### Task 1: AgentBase scaffold files

**Files:**
- Create: `main.py` (repo root) — placeholder, replaced in Task 7
- Create/replace: `requirements.txt`
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `.env.example`
- Create: `.greennode.json`
- Modify: `.gitignore` (add SDK/state files)

- [ ] **Step 1: `requirements.txt`**

```
greennode-agentbase
greennode-agent-bridge[langgraph]
langgraph>=1.0.0,<2.0.0
langchain-openai>=1.1.0,<2.0.0
python-dotenv
pandas==2.*
duckdb==1.*
pyarrow==17.*
statsmodels==0.14.*
ruptures==1.1.*
plotly==5.*
jinja2==3.*
httpx==0.27.*
beautifulsoup4==4.*
pytest==8.*
```

> `statsmodels` + `ruptures` power the Plan 2A analytics rigor (CausalImpact-style counterfactual, STL, change-point). Footprint-safe for 4GB; do NOT add TensorFlow CausalImpact or Prophet.

- [ ] **Step 2: `Dockerfile`** (installs our `src/gaa` package via `-e .`)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir -e .
ENV GAA_DB_PATH=/app/gaa.sqlite GAA_CACHE_DIR=/app/data/cache
EXPOSE 8080
CMD ["python", "main.py"]
```

- [ ] **Step 3: `.dockerignore`**

```
.venv/
venv/
__pycache__/
*.py[cod]
.env
.env.*
.greennode.json
.agentbase/
.agentbase-state.json
*.credentials.json
.git/
tests/
docs/
*.sqlite
data/cache/
```

- [ ] **Step 4: `.env.example`** (LangGraph + optional memory)

```
GREENNODE_CLIENT_ID=
GREENNODE_CLIENT_SECRET=
GREENNODE_AGENT_IDENTITY=
# GreenNode AI Platform (MaaS) — OpenAI-compatible. Use /agentbase-llm to get a key + model.
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
LLM_API_KEY=
LLM_MODEL=
# Optional conversation memory (use /agentbase-memory to create); blank = local MemorySaver
MEMORY_ID=
```

- [ ] **Step 5: `.greennode.json`**

```json
{"client_id": "", "client_secret": "", "agent_identity": ""}
```

- [ ] **Step 6: extend `.gitignore`** (append)

```
.greennode.json
.agentbase/
.agentbase-state.json
*.credentials.json
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt Dockerfile .dockerignore .env.example .greennode.json .gitignore
git commit -m "build: AgentBase + LangGraph scaffold (requirements, Dockerfile, env)"
```

---

### Task 2: Config — MaaS LLM env vars

**Files:**
- Modify: `src/gaa/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Update the test** (`tests/test_config.py`) to expect MaaS fields

```python
from gaa.config import Settings

def test_llm_defaults(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = Settings()
    assert s.llm_base_url.endswith("/v1")
    assert s.db_path.endswith(".sqlite")

def test_llm_env_override(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen-3-27b")
    monkeypatch.setenv("LLM_API_KEY", "k")
    s = Settings()
    assert s.llm_model == "qwen-3-27b" and s.llm_api_key == "k"
```

- [ ] **Step 2: Run — expect FAIL** (`pytest tests/test_config.py -v`) on missing attrs.

- [ ] **Step 3: Replace `src/gaa/config.py`**

```python
import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass
class Settings:
    llm_base_url: str = field(default_factory=lambda: _env(
        "LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL"))
    memory_id: str = field(default_factory=lambda: _env("MEMORY_ID"))
    db_path: str = field(default_factory=lambda: _env("GAA_DB_PATH", "gaa.sqlite"))
    cache_dir: str = field(default_factory=lambda: _env("GAA_CACHE_DIR", "data/cache"))
```

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/config.py tests/test_config.py
git commit -m "feat: MaaS LLM settings (LLM_BASE_URL/API_KEY/MODEL, MEMORY_ID)"
```

---

### Task 3: MaaS LLM client (replaces Plan 2 Task 10's real client)

**Files:**
- Create/replace: `src/gaa/llm/client.py`
- Test: `tests/llm/test_client.py` (FakeLLM tests unchanged; add adapter shape test)

The `LLM` protocol, `FakeLLM`, and `_extract_json` are exactly as in Plan 2 Task 10. Only the real client changes from Anthropic to MaaS `ChatOpenAI`.

- [ ] **Step 1: Test** (`tests/llm/test_client.py`)

```python
from gaa.llm.client import FakeLLM, LangChainMaaSLLM, _extract_json

def test_fake_llm_returns_preset():
    assert FakeLLM({"main_story": "x"}).complete_json("s", "u")["main_story"] == "x"

def test_extract_json_strips_prose():
    assert _extract_json('Sure: {"a": 1} done')["a"] == 1

def test_maas_client_exposes_complete_json():
    assert hasattr(LangChainMaaSLLM, "complete_json")
```

- [ ] **Step 2: Run — expect FAIL** (`LangChainMaaSLLM` missing).

- [ ] **Step 3: Implementation** (`src/gaa/llm/client.py`)

```python
import json
from typing import Optional, Protocol
from gaa.config import Settings


class LLM(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class FakeLLM:
    def __init__(self, preset: dict) -> None:
        self._preset = preset
    def complete_json(self, system: str, user: str) -> dict:
        return dict(self._preset)


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start:end + 1])


class LangChainMaaSLLM:
    """OpenAI-compatible client against GreenNode AI Platform (MaaS) via langchain-openai."""
    def __init__(self, settings: Optional[Settings] = None) -> None:
        from langchain_openai import ChatOpenAI
        s = settings or Settings()
        self._llm = ChatOpenAI(model=s.llm_model, base_url=s.llm_base_url,
                               api_key=s.llm_api_key, temperature=0)

    def complete_json(self, system: str, user: str) -> dict:
        from langchain_core.messages import SystemMessage, HumanMessage
        resp = self._llm.invoke([
            SystemMessage(content=system + "\nRespond ONLY with one valid JSON object."),
            HumanMessage(content=user),
        ])
        return _extract_json(resp.content)
```

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/llm/client.py tests/llm/test_client.py
git commit -m "feat: MaaS ChatOpenAI LLM client (replaces anthropic client)"
```

---

### Task 4: LangGraph state + GraphAgent (route + analyze)

**Files:**
- Create: `src/gaa/graph.py`
- Test: `tests/test_graph.py`
- Create: `tests/__init__.py` if missing

`GraphAgent` holds injected deps and a compiled graph; `handle()` is what `main.py` calls. State is serializable so a checkpointer can persist it.

- [ ] **Step 1: Test** (`tests/test_graph.py`)

```python
import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from gaa.graph import GraphAgent
from gaa.engine import AttributionEngine
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.onboarding.profiler import Profiler
from gaa.schema.profile import GameProfile, ColumnMapping

def _deps(tmp_path):
    ps = ProfileStore(str(tmp_path / "p.sqlite"))
    ms = MetricsStore(str(tmp_path / "m"))
    prof = GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={}))
    ps.save(prof); ps.set_active("MyGame")
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    ms.save("MyGame", df)
    llm = FakeLLM({"main_story": "Mostly internal.",
                   "causes": {"internal": [], "market": []},
                   "scenarios": [], "risks": [], "assumptions_and_gaps": []})
    engine = AttributionEngine(llm, FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
                               FixtureSignalsSource([]))
    return dict(engine=engine, profile_store=ps, metrics_store=ms,
                benchmark=FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
                profiler=Profiler(llm), checkpointer=MemorySaver())

def test_analyze_turn_returns_html_and_summary(tmp_path):
    agent = GraphAgent(**_deps(tmp_path))
    out = agent.handle({"message": "why did dau drop?"}, session_id="s1", user_id="u1")
    assert out["mode"] == "analyze"
    assert "Mostly internal." in out["markdown_summary"]
    assert "<html" in out["html"].lower()

def test_setup_turn_when_no_profile(tmp_path):
    d = _deps(tmp_path)
    # wipe active profile to force setup
    d["profile_store"] = ProfileStore(str(tmp_path / "empty.sqlite"))
    agent = GraphAgent(**d)
    out = agent.handle({"message": "hello"}, session_id="s2", user_id="u2")
    assert out["mode"] == "setup"
```

- [ ] **Step 2: Run — expect FAIL** (`gaa.graph` missing).

- [ ] **Step 3: Implementation** (`src/gaa/graph.py`)

```python
from typing import Annotated, Optional, TypedDict
import pandas as pd
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from gaa.engine import AttributionEngine
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.sources.base import BenchmarkSource
from gaa.onboarding.profiler import Profiler
from gaa.orchestrator.router import classify_intent
from gaa.render.markdown import to_markdown
from gaa.render.report import render_report


class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    mode: str
    result: dict            # serialized response for this turn
    pending_mapping: dict   # onboarding: proposed mapping awaiting confirm
    pending_meta: dict      # onboarding: {name, platform, genre, adapter, csv_path}


class GraphAgent:
    def __init__(self, engine: AttributionEngine, profile_store: ProfileStore,
                 metrics_store: MetricsStore, benchmark: BenchmarkSource,
                 profiler: Profiler, checkpointer=None) -> None:
        self._engine = engine
        self._profiles = profile_store
        self._metrics = metrics_store
        self._benchmark = benchmark
        self._profiler = profiler
        self._graph = self._build(checkpointer)

    # ---- nodes ----
    def _route(self, state: State) -> dict:
        msg = state["messages"][-1].content if state["messages"] else ""
        has_profile = self._profiles.get_active() is not None
        # a pending onboarding confirm short-circuits to setup
        if state.get("pending_mapping"):
            return {"mode": "setup"}
        return {"mode": classify_intent(msg, has_active_profile=has_profile)}

    def _analyze(self, state: State) -> dict:
        msg = state["messages"][-1].content
        profile = self._profiles.get_active()
        df = self._metrics.load(profile.name)
        res = self._engine.analyze_full(profile, df, msg)
        series = (df[df["metric"] == res.metric].groupby("date")["value"].sum().sort_index()
                  if res.metric else df.groupby("date")["value"].sum())
        genre = (self._benchmark.genre_trend(profile.genre, res.start, res.end)
                 if res.start and res.end else {})
        html = render_report(res.hypothesis, metric=res.metric or "metric",
                             start=res.start or "", end=res.end or "",
                             series=series, genre_trend=genre)
        return {"result": {"mode": "analyze", "hypothesis": res.hypothesis.model_dump(),
                           "markdown_summary": to_markdown(res.hypothesis), "html": html}}

    def _setup(self, state: State) -> dict:
        # Plan 0 Task 5 fills propose/confirm; minimal setup reply here
        return {"result": {"mode": "setup",
                           "message": "Let's connect your data. Send your CSV path to onboard "
                                      "(action=onboard), I'll propose a column mapping to confirm."}}

    def _build(self, checkpointer):
        g = StateGraph(State)
        g.add_node("route", self._route)
        g.add_node("analyze", self._analyze)
        g.add_node("setup", self._setup)
        g.add_edge(START, "route")
        g.add_conditional_edges("route", lambda s: s["mode"],
                                {"analyze": "analyze", "setup": "setup"})
        g.add_edge("analyze", END)
        g.add_edge("setup", END)
        return g.compile(checkpointer=checkpointer)

    # ---- public ----
    def handle(self, payload: dict, session_id: str, user_id: str) -> dict:
        message = payload.get("message", "")
        config = {"configurable": {"thread_id": session_id or "local",
                                   "actor_id": user_id or "local"}}
        out = self._graph.invoke({"messages": [("user", message)]}, config)
        return out["result"]
```

- [ ] **Step 4: Run — expect PASS** (`pytest tests/test_graph.py -v`).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/graph.py tests/test_graph.py
git commit -m "feat: LangGraph GraphAgent (route + analyze nodes over the engine)"
```

> **Note — surface the run trace in runtime logs.** The per-run reasoning trace from **[Plan 2 · Task 15](2026-06-10-game-attribution-agent-plan-2-analysis-engine.md)** rides on `res.hypothesis.trace` and already leaves the agent inside the `/invocations` response (it's part of `res.hypothesis.model_dump()`), and is rendered as the report panel via **[Plan 3 · Task 7](2026-06-10-game-attribution-agent-plan-3-onboarding-renderer-demo.md)**. But **`/agentbase-monitor` runtime logs only capture stdout/stderr** — so emit a one-line summary in `_analyze` so a deployed run is debuggable from the logs alone (e.g. spotting a module that silently went `data_gap` or `error` in prod). Add at module top `import logging; log = logging.getLogger("gaa.graph")`, then before the `_analyze` return:
>
> ```python
>         tr = res.hypothesis.trace
>         if tr:
>             log.info("analyze trace (%s findings): %s", tr.total_entries,
>                      " → ".join(f"{e.module}:{e.status}({e.entries_added})" for e in tr.events))
> ```
>
> Pure observability — no test or return-shape change (the response already carries `hypothesis.trace`). Reads in logs as e.g. `analyze trace (4 findings): anomaly:ok(1) → segment:ok(1) → market:ok(1) → competitor:data_gap(1)`. View with `/agentbase-monitor`.

---

### Task 5: Onboarding nodes (multi-turn propose → confirm)

**Files:**
- Modify: `src/gaa/graph.py` (richer `_setup` + a `payload`-driven onboarding path)
- Test: `tests/test_graph_onboarding.py`

Onboarding uses the existing `Profiler` (Plan 3 Task 4) + adapters/stores (Plan 1). Two payload actions drive it without parsing free text: `{"action":"onboard_propose","csv_path":...,"adapter":...}` and `{"action":"onboard_confirm", ...mapping..., "name", "platform", "genre"}`. Free-text "connect my data" still routes to a setup hint.

- [ ] **Step 1: Test** (`tests/test_graph_onboarding.py`)

```python
from langgraph.checkpoint.memory import MemorySaver
from gaa.graph import GraphAgent
from gaa.engine import AttributionEngine
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.onboarding.profiler import Profiler

def _agent(tmp_path):
    llm = FakeLLM({"date_col": "Date", "metric_cols": {"DAU": "dau"},
                   "dim_cols": {"Country": "region"}})
    engine = AttributionEngine(llm, FixtureBenchmarkSource({}), FixtureSignalsSource([]))
    return GraphAgent(engine=engine,
                      profile_store=ProfileStore(str(tmp_path / "p.sqlite")),
                      metrics_store=MetricsStore(str(tmp_path / "m")),
                      benchmark=FixtureBenchmarkSource({}), profiler=Profiler(llm),
                      checkpointer=MemorySaver())

def test_onboard_propose_then_confirm(tmp_path):
    agent = _agent(tmp_path)
    p = agent.handle({"action": "onboard_propose", "adapter": "csv",
                      "csv_path": "src/gaa/data/sample/roblox_export.csv"},
                     session_id="s", user_id="u")
    assert p["mode"] == "setup" and p["mapping"]["date_col"] == "Date"

    c = agent.handle({"action": "onboard_confirm", "name": "MyGame", "platform": "roblox",
                      "genre": "survival", "adapter": "csv",
                      "csv_path": "src/gaa/data/sample/roblox_export.csv",
                      "mapping": {"date_col": "Date", "metric_cols": {"DAU": "dau"}, "dim_cols": {}}},
                     session_id="s", user_id="u")
    assert c["mode"] == "setup" and c["row_count"] == 6
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Update `GraphAgent.handle` to dispatch onboarding actions before the graph**

In `src/gaa/graph.py`, add imports and an action dispatcher; the graph still handles free-text turns.

```python
import pandas as pd
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.adapters.roblox_adapter import RobloxAdapter

# inside GraphAgent:
    def _onboard_propose(self, payload: dict) -> dict:
        sample = pd.read_csv(payload["csv_path"]).head(20)
        mapping = self._profiler.propose(sample)
        return {"mode": "setup", "mapping": mapping.model_dump(),
                "message": self._profiler.confirmation_message(mapping)}

    def _onboard_confirm(self, payload: dict) -> dict:
        mapping = ColumnMapping(**payload["mapping"])
        adapter = RobloxAdapter() if payload["adapter"] == "roblox" else CSVAdapter()
        df = adapter.load(payload["csv_path"], mapping)
        self._metrics.save(payload["name"], df)
        self._profiles.save(GameProfile(name=payload["name"], platform=payload["platform"],
                                        genre=payload["genre"], mapping=mapping))
        self._profiles.set_active(payload["name"])
        return {"mode": "setup", "name": payload["name"], "row_count": int(len(df)),
                "metrics": sorted(df["metric"].unique().tolist())}

    def handle(self, payload: dict, session_id: str, user_id: str) -> dict:
        action = payload.get("action")
        if action == "onboard_propose":
            return self._onboard_propose(payload)
        if action == "onboard_confirm":
            return self._onboard_confirm(payload)
        message = payload.get("message", "")
        config = {"configurable": {"thread_id": session_id or "local",
                                   "actor_id": user_id or "local"}}
        out = self._graph.invoke({"messages": [("user", message)]}, config)
        return out["result"]
```

> The `RobloxAdapter().load(path, mapping)` 2-arg call matches Plan 1 Task 5. `CSVAdapter().load(path, mapping)` matches Plan 1 Task 4.

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/graph.py tests/test_graph_onboarding.py
git commit -m "feat: onboarding propose/confirm actions on GraphAgent"
```

---

### Task 6: Checkpointer factory (AgentBase Memory in prod, MemorySaver locally)

**Files:**
- Create: `src/gaa/memory.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Test** (`tests/test_memory.py`)

```python
from gaa.memory import make_checkpointer

def test_local_checkpointer_when_no_memory_id(monkeypatch):
    monkeypatch.delenv("MEMORY_ID", raising=False)
    cp = make_checkpointer()
    from langgraph.checkpoint.memory import MemorySaver
    assert isinstance(cp, MemorySaver)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implementation** (`src/gaa/memory.py`)

```python
import os


def make_checkpointer():
    """AgentBase Memory checkpointer when MEMORY_ID is set; else in-process MemorySaver."""
    memory_id = os.environ.get("MEMORY_ID", "")
    if memory_id:
        from greennode_agent_bridge import AgentBaseMemoryEvents
        return AgentBaseMemoryEvents(memory_id=memory_id)
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
```

- [ ] **Step 4: Run — expect PASS.** Commit:

```bash
git add src/gaa/memory.py tests/test_memory.py
git commit -m "feat: checkpointer factory (AgentBase Memory or local MemorySaver)"
```

---

### Task 7: `main.py` — AgentBase SDK entrypoint

**Files:**
- Replace: `main.py` (repo root)

> `main.py` is thin glue (SDK ↔ GraphAgent) and is verified by the local smoke + deploy health check, not a unit test (the SDK provides the HTTP server). Build the agent once at module load.

- [ ] **Step 1: Write `main.py`**

```python
import os
from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, RequestContext, PingStatus

from gaa.config import Settings
from gaa.engine import AttributionEngine
from gaa.llm.client import LangChainMaaSLLM
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.onboarding.profiler import Profiler
from gaa.sources.roblox_benchmark import RoMonitorBenchmark
from gaa.sources.web_signals import WebSignalsSource
from gaa.memory import make_checkpointer
from gaa.graph import GraphAgent

load_dotenv()
app = GreenNodeAgentBaseApp()

_s = Settings()
_llm = LangChainMaaSLLM(_s)
_benchmark = RoMonitorBenchmark(
    cache_dir=_s.cache_dir + "/benchmark",
    genre_url_tmpl=os.environ.get("GAA_BENCHMARK_URL_TMPL", "https://example/{genre}.json"))
_signals = WebSignalsSource(
    cache_dir=_s.cache_dir + "/signals",
    query_url_tmpl=os.environ.get("GAA_SIGNALS_URL_TMPL", "https://example/news?q={game}"))
_agent = GraphAgent(
    engine=AttributionEngine(_llm, _benchmark, _signals),
    profile_store=ProfileStore(_s.db_path),
    metrics_store=MetricsStore(_s.cache_dir + "/metrics"),
    benchmark=_benchmark,
    profiler=Profiler(_llm),
    checkpointer=make_checkpointer(),
)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    try:
        return {"status": "success",
                **_agent.handle(payload, context.session_id, context.user_id)}
    except Exception as exc:  # graceful degradation — never 500 the judge's request
        return {"status": "error", "error": str(exc)}


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
```

- [ ] **Step 2: Local smoke (requires `pip install -r requirements.txt` + a MaaS key in `.env`)**

```bash
python main.py &   # starts on :8080
sleep 3
curl -s localhost:8080/health
curl -s -X POST localhost:8080/invocations -H 'content-type: application/json' \
  -H 'X-GreenNode-AgentBase-Session-Id: s1' -H 'X-GreenNode-AgentBase-User-Id: u1' \
  -d '{"message":"hello"}'
kill %1
```
Expected: health 200; invocations returns a JSON object with `status`. (A "setup" reply is fine before any profile exists.)

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: AgentBase SDK entrypoint wiring GraphAgent"
```

---

### Task 8: Deploy to AgentBase (via installed skills)

> Platform steps — driven by the installed skills, which hold the authoritative APIs. Each skill enforces a confirm gate; follow its prompts. Capture IDs/URLs into the README as you go.

- [ ] **Step 1: IAM credentials.** Ensure `GREENNODE_CLIENT_ID` / `GREENNODE_CLIENT_SECRET` are set (IAM service account at https://iam.console.vngcloud.vn/service-accounts). Verify: `bash .claude/skills/agentbase/scripts/check_credentials.sh iam`.

- [ ] **Step 2: MaaS LLM key + model.** Invoke `/agentbase-llm`: list/create an API key (saved to `.env` as `LLM_API_KEY`), set `LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`, and pick an `ENABLED` model — set `LLM_MODEL` to the model's `path`.

- [ ] **Step 3: (Optional) Memory.** If multi-turn memory is wanted in prod, invoke `/agentbase-memory create` and set `MEMORY_ID` in `.env`. Otherwise leave blank (local MemorySaver; per-process only).

- [ ] **Step 4: Deploy.** Invoke `/agentbase-deploy` (Custom Agent path): it builds the image (`--platform linux/amd64`), pushes to the managed Container Registry (`--from-cr`), creates the runtime with `--env-file .env`, and polls to ACTIVE. Pick a flavor (e.g. `1x1-general`; bump if `OOMKilled`).

- [ ] **Step 5: Verify (satisfies pass/fail #1).**

```bash
# endpoint URL from /agentbase-deploy output
curl -s -o /dev/null -w "%{http_code}" "<endpoint-url>/health"
curl -s -X POST "<endpoint-url>/invocations" -H 'content-type: application/json' \
  -H 'X-GreenNode-AgentBase-Session-Id: judge' -H 'X-GreenNode-AgentBase-User-Id: judge' \
  -d '{"message":"what is going on with my game?"}'
```
Expected: health 200; invocations returns a JSON `AttributionHypothesis` payload (or a setup reply if no profile is onboarded yet).

- [ ] **Step 6: Record deploy details + model declaration in README** (Task 9).

---

### Task 9: README, model declaration, demo snapshot

**Files:**
- Create/replace: `README.md`
- Create: `src/gaa/data/snapshots/hero.json` (from a real run via the graph)
- Create: `docs/demo-script.md`, `docs/submission-form.md`

- [ ] **Step 1: README** — overwrite with the AgentBase-accurate version (sections: what it does; run locally `python main.py`; `POST /invocations` payloads — `{"message": ...}`, `{"action":"onboard_propose"|"onboard_confirm", ...}`; **Models: GreenNode AI Platform MaaS via `LLM_*`, external models declared if used**; Data: public/aggregate/PII-stripped; **Deployment: exact `/agentbase-deploy` steps + runtime ID + endpoint URL**).

- [ ] **Step 2: Hero snapshot** — run the deployed agent once on the real Roblox demo case, save `{hypothesis, markdown_summary, html}` to `src/gaa/data/snapshots/hero.json`. Use it as the guaranteed-good demo fallback (open the `html` in a browser for the video).

- [ ] **Step 3: `docs/demo-script.md`** (2-act, per Plan 3 Task 10) and `docs/submission-form.md` (≤300-char summary + the pass/fail checklist), adjusted to `/invocations` calls.

- [ ] **Step 4: Commit**

```bash
git add README.md src/gaa/data/snapshots/hero.json docs/demo-script.md docs/submission-form.md
git commit -m "docs: README (AgentBase), model declaration, demo snapshot + scripts"
```

---

## Self-Review (completed during authoring)

**Coverage of the platform/integration delta:** scaffold files (Task 1) ✓; MaaS config + LLM client (Tasks 2, 3) ✓; LangGraph state/route/analyze (Task 4; analyze node logs the run trace to stdout for /agentbase-monitor) ✓; multi-turn onboarding nodes (Task 5) ✓; memory checkpointer (Task 6) ✓; SDK `main.py` entrypoint (Task 7) ✓; deploy via skills (Task 8) ✓; README/declaration/snapshot (Task 9) ✓. Supersession map reconciles every superseded earlier task.

**Placeholder scan:** none. `GAA_BENCHMARK_URL_TMPL` / `GAA_SIGNALS_URL_TMPL` are env-configured live endpoints (the "confirm at build time" seam noted in Plan 3 Tasks 2–3), not gaps.

**Type consistency:** `LLM.complete_json(system,user)->dict` + `FakeLLM` identical to Plan 2 Task 10 → `Synthesizer`/`Profiler` consume it unchanged. `AttributionEngine.analyze_full -> AnalysisResult(hypothesis,metric,start,end)` matches Plan 3 Task 8. `render_report(h, metric, start, end, series, genre_trend)` matches Plan 3 Task 7. `classify_intent(message, has_active_profile)` matches Plan 3 Task 9. `to_markdown(h)` matches Plan 2 Task 13. `Profiler.propose(sample)->ColumnMapping` / `confirmation_message(mapping)` match Plan 3 Task 4. `ProfileStore`/`MetricsStore`/`CSVAdapter`/`RobloxAdapter` signatures match Plan 1 Tasks 4–6 + Plan 2 Task 4. `BenchmarkSource.genre_trend` matches Plan 2 Task 5 / Plan 3 Task 2. SDK shapes (`GreenNodeAgentBaseApp`, `@app.entrypoint`, `@app.ping`, `RequestContext.session_id/user_id`, `AgentBaseMemoryEvents(memory_id=...)`, `ChatOpenAI(model,base_url,api_key)`) match the AgentBase templates verbatim.
