import pandas as pd
from gaa.modules.market_benchmark import MarketBenchmark
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.fixtures import FixtureBenchmarkSource
from gaa.schema.profile import GameProfile, ColumnMapping


def _ctx(metrics_df, start, end, changepoint=None):
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    ctx = AnalysisContext(profile=prof, metrics=metrics_df, query="q", metric="dau",
                          start=start, end=end, direction="down")
    if changepoint:
        ctx.extras["changepoint"] = changepoint
    return ctx


def _df(vals, start="2026-04-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D")
    df = pd.DataFrame({"date": idx, "metric": "dau", "value": [float(v) for v in vals]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    return df


def test_causal_path_flags_internal_when_control_holds():
    target = [100] * 14 + [60, 61, 59]
    df = _df(target)
    bench = FixtureBenchmarkSource(genre_index={d.strftime("%Y-%m-%d"): 100.0
                                                for d in pd.date_range("2026-04-01", periods=17)})
    led = EvidenceLedger()
    MarketBenchmark(bench).run(_ctx(df, "2026-04-01", "2026-04-17", changepoint="2026-04-15"), led)
    e = [x for x in led.all() if x.module == "market"][0]
    assert "counterfactual" in e.claim.lower() or "market" in e.claim.lower()
    assert e.source_type == "derived"


def test_fallback_indexed_comparison_on_sparse_history():
    df = _df([1000, 600], start="2026-05-01")
    bench = FixtureBenchmarkSource(genre_index={"2026-05-01": 100.0, "2026-05-02": 98.0})
    led = EvidenceLedger()
    MarketBenchmark(bench).run(_ctx(df, "2026-05-01", "2026-05-02"), led)
    assert any(x.module == "market" for x in led.all())


def test_records_gap_when_no_benchmark():
    df = _df([1000, 600], start="2026-05-01")
    led = EvidenceLedger()
    MarketBenchmark(FixtureBenchmarkSource(genre_index={})).run(_ctx(df, "2026-05-01", "2026-05-02"), led)
    assert any(e.strength == "low" and e.source_type == "derived" for e in led.all())
