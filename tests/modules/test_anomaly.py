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


def test_requested_metric_absent_falls_back_to_available():
    # query "retention" mis-routed to retention_d7, which has NO rows -> empty
    # series -> +0% change and a NaT window. Must fall back to a metric present
    # in the data instead of analyzing nothing.
    ctx = _ctx(metric="retention_d7")  # the fixture only contains 'dau'
    led = EvidenceLedger()
    AnomalyDetection().run(ctx, led)
    assert ctx.metric == "dau", "must fall back to an available metric"
    assert ctx.start and ctx.start != "NaT" and "NaT" not in str(ctx.start)
    assert any(e.module == "anomaly" and "dau" in e.claim for e in led.all())


def _retention_by_source_ctx():
    """retention_d1 with a pre-aggregated 'Total' row plus channels — the headline
    series must follow 'Total', NOT the sum of all rows (which double-counts)."""
    rows = []
    daily = {  # source -> (start_val, end_val)
        "Total": (0.022, 0.034), "Search": (0.014, 0.022), "Friends": (0.012, 0.020),
    }
    for src, (a, b) in daily.items():
        rows += [{"date": "2026-06-03", "metric": "retention_d1", "value": a, "source": src},
                 {"date": "2026-06-08", "metric": "retention_d1", "value": b, "source": src}]
    df = pd.DataFrame(rows)
    for c in ["platform", "region", "version", "cohort", "device"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    prof = GameProfile(name="G", platform="Custom", genre="shopping",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "retention_d1"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="retention_d1")


def test_rate_metric_uses_total_row_not_sum_of_segments():
    ctx = _retention_by_source_ctx()
    led = EvidenceLedger()
    AnomalyDetection().run(ctx, led)
    e = next(x for x in led.all() if x.module == "anomaly")
    # Total: 0.022 -> 0.034 == +55%. Summing all 3 rows would be ~+53% on a
    # meaningless 2x-inflated base; the giveaway is the change must track Total.
    assert "+55%" in e.claim or "+54%" in e.claim or "+56%" in e.claim, e.claim


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
