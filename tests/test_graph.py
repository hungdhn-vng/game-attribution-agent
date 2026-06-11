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
    ps.save(prof)
    ps.set_active("MyGame")
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    ms.save("MyGame", df)
    llm = FakeLLM({"main_story": "Mostly internal.",
                   "causes": {"internal": [], "market": []},
                   "scenarios": [], "risks": [], "assumptions_and_gaps": []})
    bench = FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0})
    engine = AttributionEngine(llm, bench, FixtureSignalsSource([]))
    return dict(engine=engine, profile_store=ps, metrics_store=ms,
                benchmark=bench, profiler=Profiler(llm), checkpointer=MemorySaver())


def test_analyze_turn_returns_html_and_summary(tmp_path):
    agent = GraphAgent(**_deps(tmp_path))
    out = agent.handle({"message": "why did dau drop?"}, session_id="s1", user_id="u1")
    assert out["mode"] == "analyze"
    assert "Mostly internal." in out["markdown_summary"]
    assert "<html" in out["html"].lower()


def test_setup_turn_when_no_profile(tmp_path):
    d = _deps(tmp_path)
    d["profile_store"] = ProfileStore(str(tmp_path / "empty.sqlite"))  # no active profile
    agent = GraphAgent(**d)
    out = agent.handle({"message": "hello"}, session_id="s2", user_id="u2")
    assert out["mode"] == "setup"
