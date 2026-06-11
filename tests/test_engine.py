import pandas as pd
from gaa.engine import AttributionEngine
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping


def _profile():
    return GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="Date",
                                             metric_cols={"DAU": "dau"}, dim_cols={}))


def _metrics():
    rows = []
    for d, sea, na in [("2026-05-01", 1000, 800), ("2026-05-03", 400, 770)]:
        rows += [{"date": d, "metric": "dau", "value": float(sea), "region": "SEA"},
                 {"date": d, "metric": "dau", "value": float(na), "region": "NA"}]
    df = pd.DataFrame(rows)
    for c in ["platform", "version", "cohort", "device", "source"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_engine_produces_hypothesis_with_evidence():
    preset = {"main_story": "Mostly internal — SEA fell.",
              "causes": {"internal": [{"claim": "SEA collapse", "evidence_ids": ["L1", "L2"],
                                        "likelihood": "Likely"}],
                         "market": [{"claim": "genre flat", "evidence_ids": ["L3"],
                                     "likelihood": "Possible"}]},
              "scenarios": [], "risks": [], "assumptions_and_gaps": []}
    engine = AttributionEngine(
        llm=FakeLLM(preset),
        benchmark=FixtureBenchmarkSource({"2026-05-01": 100.0, "2026-05-03": 98.0}),
        signals=FixtureSignalsSource([{"date": "2026-05-02", "title": "patch v3.2",
                                       "kind": "patch", "url": "u", "sentiment": -0.1}]))
    h = engine.analyze(_profile(), _metrics(), "what happened to my game?")
    assert h.main_story.startswith("Mostly internal")
    assert len(h.evidence) >= 3  # anomaly + segment + market + signal
    assert h.causes.internal and h.causes.internal[0].evidence_quality in (
        "Strong", "Moderate", "Weak")
