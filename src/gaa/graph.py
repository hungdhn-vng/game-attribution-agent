from typing import Annotated, TypedDict
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
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.adapters.roblox_adapter import RobloxAdapter


class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    mode: str
    result: dict
    pending_mapping: dict


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
        msg = state["messages"][-1].content if state.get("messages") else ""
        has_profile = self._profiles.get_active() is not None
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
        return {"result": {"mode": "setup",
                           "message": "Let's connect your data. Send your CSV path to onboard "
                                      "(action=onboard_propose); I'll propose a column mapping to confirm."}}

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

    # ---- onboarding actions (payload-driven, no free-text parsing) ----
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

    # ---- public ----
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
