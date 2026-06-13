import pandas as pd
from gaa.core.modules.market_benchmark import MarketBenchmark
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.sources.fixtures import FixtureBenchmarkSource
from gaa.core.schema.profile import GameProfile, ColumnMapping


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


# ---------------------------------------------------------------------------
# Qualitative tier tests (Task A9a)
# ---------------------------------------------------------------------------

class _SourceWithQual:
    """Stub benchmark source: no quant data, but exposes qualitative_context."""
    def genre_trend(self, genre, start, end):
        return {}  # empty → triggers gap branch

    def qualitative_context(self, genre):
        return {
            "direction": "down",
            "summary": "Players are churning due to new competitor",
            "citations": [{"url": "https://example.com/report"}],
        }


def test_qualitative_context_emits_external_low_entry():
    """When quant data is absent but qualitative_context is available, a 'market context' entry
    with source_type='external' and strength='low' is added to the ledger."""
    df = _df([1000, 600], start="2026-05-01")
    led = EvidenceLedger()
    MarketBenchmark(_SourceWithQual()).run(_ctx(df, "2026-05-01", "2026-05-02"), led)

    qual_entries = [e for e in led.all()
                    if e.module == "market" and e.source_type == "external" and e.strength == "low"]
    assert qual_entries, "expected an external/low market context entry"
    entry = qual_entries[0]
    assert "market context" in entry.claim.lower()
    assert "down" in entry.claim or "down" == entry.value
    assert entry.source == "https://example.com/report"


class _SourceWithStringCitations:
    """Stub source whose qual payload carries citations as plain URL strings,
    as persisted by crawls that stored the raw Perplexity citation list."""
    def genre_trend(self, genre, start, end):
        return {}

    def qualitative_context(self, genre):
        return {
            "direction": "down",
            "summary": "Players are churning due to new competitor",
            "citations": ["https://example.com/report"],
        }


def test_qualitative_context_tolerates_string_citations():
    """Persisted qual payloads may hold citations as URL strings — the module
    must not crash and must still cite the URL as the entry source."""
    df = _df([1000, 600], start="2026-05-01")
    led = EvidenceLedger()
    MarketBenchmark(_SourceWithStringCitations()).run(_ctx(df, "2026-05-01", "2026-05-02"), led)

    qual_entries = [e for e in led.all()
                    if e.module == "market" and e.source_type == "external" and e.strength == "low"]
    assert qual_entries, "expected an external/low market context entry"
    assert qual_entries[0].source == "https://example.com/report"


def test_fixture_source_without_qualitative_context_no_crash():
    """FixtureBenchmarkSource (no qualitative_context method) must not crash — only the
    gap entry is emitted (derived/low), no external entry."""
    df = _df([1000, 600], start="2026-05-01")
    led = EvidenceLedger()
    MarketBenchmark(FixtureBenchmarkSource(genre_index={})).run(_ctx(df, "2026-05-01", "2026-05-02"), led)

    # At least one gap entry present
    assert any(e.source_type == "derived" and e.strength == "low" for e in led.all())
    # No external entry (source doesn't expose qualitative_context)
    assert not any(e.source_type == "external" for e in led.all())
