import pandas as pd
from gaa.core.modules.anomaly import AnomalyDetection
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


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


def _multi_metric_ctx():
    """retention_d1: big % swing but within noise (low z); revenue: material + anomalous (high z)."""
    dates = pd.date_range("2026-06-01", periods=8, freq="D")
    ret = [0.30, 0.52, 0.28, 0.55, 0.33, 0.50, 0.40, 0.50]
    rev = [1000, 980, 950, 900, 870, 820, 780, 720]
    rows = []
    for d, r, v in zip(dates, ret, rev):
        rows += [{"date": d, "metric": "retention_d1", "value": float(r)},
                 {"date": d, "metric": "revenue", "value": float(v)}]
    df = pd.DataFrame(rows)
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    prof = GameProfile(name="G", platform="custom", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return df, prof


def test_scan_ranks_by_anomaly_significance_not_raw_percent():
    df, prof = _multi_metric_ctx()
    ctx = AnalysisContext(profile=prof, metrics=df, query="what is going on?", metric=None)
    led = EvidenceLedger()
    AnomalyDetection().run(ctx, led)
    # must surface the statistically anomalous + material move (revenue), NOT the noisy rate
    assert ctx.metric == "revenue"
    assert "revenue" in next(e for e in led.all() if e.module == "anomaly").claim


def test_large_percent_but_low_z_is_not_high_strength():
    df, prof = _multi_metric_ctx()
    ctx = AnalysisContext(profile=prof, metrics=df, query="q", metric="retention_d1")
    led = EvidenceLedger()
    AnomalyDetection().run(ctx, led)
    e = next(x for x in led.all() if x.module == "anomaly")
    assert e.strength != "high"   # +66% at z~0.85 is noise, must not be flagged high
