"""External modules must degrade gracefully when a source RAISES (e.g. network/DNS failure),
emitting a data-gap ledger entry instead of crashing the engine."""
import pandas as pd
from gaa.core.modules.market_benchmark import MarketBenchmark
from gaa.core.modules.competitor_signals import CompetitorSignals
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


class _RaisingBenchmark:
    def genre_trend(self, genre, start, end):
        raise OSError("Name or service not known")


class _RaisingSignals:
    def events(self, game, genre, start, end):
        raise OSError("Name or service not known")


def _ctx():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
                       "metric": ["dau", "dau"], "value": [1000.0, 600.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-05-01", end="2026-05-03", direction="down")


def test_market_module_degrades_on_source_error():
    led = EvidenceLedger()
    MarketBenchmark(_RaisingBenchmark()).run(_ctx(), led)  # must NOT raise
    e = [x for x in led.all() if x.module == "market"][0]
    assert e.source_type == "derived" and e.strength == "low" and "unavailable" in e.claim.lower()


def test_competitor_module_degrades_on_source_error():
    led = EvidenceLedger()
    CompetitorSignals(_RaisingSignals()).run(_ctx(), led)  # must NOT raise
    e = [x for x in led.all() if x.module == "competitor"][0]
    assert e.source_type == "derived" and e.strength == "low" and "unavailable" in e.claim.lower()
