import pandas as pd
from gaa.modules.competitor_signals import CompetitorSignals
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.fixtures import FixtureSignalsSource
from gaa.schema.profile import GameProfile, ColumnMapping


def _ctx():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01"]), "metric": ["dau"], "value": [1.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    prof = GameProfile(name="MyGame", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-04-01", end="2026-05-31", direction="down")


def test_logs_events_as_external_entries():
    src = FixtureSignalsSource(events=[
        {"date": "2026-04-28", "title": "Competitor Y soft-launch", "kind": "competitor",
         "url": "http://x", "sentiment": -0.3},
        {"date": "2026-05-04", "title": "v3.2 update notes", "kind": "patch",
         "url": "http://p", "sentiment": 0.0}])
    led = EvidenceLedger()
    CompetitorSignals(src).run(_ctx(), led)
    ext = [e for e in led.all() if e.module == "competitor" and e.source_type == "external"]
    assert len(ext) == 2
    assert any("Competitor Y" in e.claim for e in ext)


def test_no_events_records_gap():
    led = EvidenceLedger()
    CompetitorSignals(FixtureSignalsSource(events=[])).run(_ctx(), led)
    assert any(e.source_type == "derived" and e.strength == "low" for e in led.all())
