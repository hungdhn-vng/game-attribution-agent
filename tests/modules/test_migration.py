# tests/modules/test_migration.py
import pandas as pd
from gaa.core.modules.migration import MigrationPattern
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _ctx(changepoint="2026-06-05"):
    prof = GameProfile(name="g", platform="roblox", genre="rpg",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    df = pd.DataFrame({"date": pd.to_datetime(["2026-06-04"]), "metric": ["dau"], "value": [1.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    ctx = AnalysisContext(profile=prof, metrics=df, query="q", metric="retention_d1",
                          start="2026-06-01", end="2026-06-08")
    ctx.extras["changepoint"] = changepoint
    return ctx


def _seed(led, *, market_claim, signal_claim, signal_date="2026-06-04"):
    led.add(module="market", claim=market_claim, value="v", source="b",
            source_type="external", strength="med", timeframe="2026-06-01..2026-06-08")
    led.add(module="competitor", claim=signal_claim, value="v", source="https://yt",
            source_type="external", strength="med", timeframe=signal_date)


def test_emits_migration_when_pattern_present():
    led = EvidenceLedger()
    _seed(led, market_claim="retention_d1 ≈ 3% vs rpg benchmark 12%–19% → underperforming the market",
          signal_claim="external (influencer): BigTuber on 2026-06-04 — may explain the move: X blew up")
    MigrationPattern().run(_ctx(), led)
    m = [e for e in led.all() if e.module == "migration"]
    assert m and "migration" in m[0].claim.lower() and m[0].source_type == "derived"
    assert m[0].strength == "med"  # timing near change-point


def test_no_migration_without_competitor_signal():
    led = EvidenceLedger()
    _seed(led, market_claim="… underperforming the market",
          signal_claim="genre social trend (social_trend): generic buzz")  # not influencer/competitor_event
    MigrationPattern().run(_ctx(), led)
    assert not [e for e in led.all() if e.module == "migration"]


def test_no_migration_without_game_specific_market():
    led = EvidenceLedger()
    _seed(led, market_claim="genre trending flat",
          signal_claim="external (influencer): BigTuber on 2026-06-04 — X blew up")
    MigrationPattern().run(_ctx(), led)
    assert not [e for e in led.all() if e.module == "migration"]
