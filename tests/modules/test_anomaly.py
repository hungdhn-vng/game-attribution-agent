import pandas as pd
from gaa.modules.anomaly import AnomalyDetection
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.profile import GameProfile, ColumnMapping


def _ctx(metric=None):
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]),
        "metric": ["dau", "dau", "dau"],
        "value": [1000.0, 980.0, 600.0],
        "platform": [None]*3, "region": [None]*3, "version": [None]*3,
        "cohort": [None]*3, "device": [None]*3, "source": [None]*3,
    })
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="what happened", metric=metric)


def test_quantifies_specified_metric_drop():
    led = EvidenceLedger()
    AnomalyDetection().run(_ctx(metric="dau"), led)
    entries = led.all()
    assert any("dau" in e.claim and e.source_type == "internal" for e in entries)
    drop = next(e for e in entries if e.module == "anomaly")
    assert "-" in drop.value  # negative change quantified


def test_scan_mode_picks_most_salient_metric():
    led = EvidenceLedger()
    AnomalyDetection().run(_ctx(metric=None), led)  # scan mode
    assert any(e.module == "anomaly" for e in led.all())
