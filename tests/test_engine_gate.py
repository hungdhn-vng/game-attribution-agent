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
