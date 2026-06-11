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
