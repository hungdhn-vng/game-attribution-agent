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
    engine = AttributionEngine(
        FakeLLM({"main_story": "x", "causes": {"internal": [], "market": []},
                 "scenarios": [], "risks": [], "assumptions_and_gaps": []}),
        FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 99.0}),
        FixtureSignalsSource([]))
    res = engine.analyze_full(_profile(), _metrics(), "what happened?")
    assert isinstance(res, AnalysisResult)
    assert res.metric == "dau"
    assert res.start == "2026-05-01" and res.end == "2026-05-03"
    assert res.hypothesis.main_story == "x"
