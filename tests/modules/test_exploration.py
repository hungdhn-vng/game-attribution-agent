# tests/modules/test_exploration.py
import pandas as pd
import pytest
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.schema.canonical import CANONICAL_DIMS

DIMS = CANONICAL_DIMS


def _profile():
    return GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}))


def _frame(rows: list[dict]) -> pd.DataFrame:
    """rows: dicts with at least date/metric/value (+ any dims). Fills missing dims with None."""
    df = pd.DataFrame(rows)
    for c in DIMS:
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype(float)
    df["metric"] = df["metric"].astype(str)
    return df


def _ctx(df: pd.DataFrame, metric="dau", start=None, end=None, direction="down") -> AnalysisContext:
    dates = sorted(df["date"].unique())
    return AnalysisContext(profile=_profile(), metrics=df, query="why did it change",
                           metric=metric,
                           start=start or str(pd.Timestamp(dates[0]).date()),
                           end=end or str(pd.Timestamp(dates[-1]).date()),
                           direction=direction)


def test_strength_thresholds_mirror_segment():
    from gaa.core.modules.exploration import _strength
    assert _strength(0.6) == "high"
    assert _strength(-0.5) == "high"
    assert _strength(0.3) == "med"
    assert _strength(0.1) == "low"


def test_covered_pairs_parses_segment_sources():
    from gaa.core.modules.exploration import _covered_pairs
    led = EvidenceLedger()
    led.add(module="segment", claim="region=SEA explains 40% of the dau move", value="EP 40%",
            source="internal:dau by region (Adtributor)", source_type="internal", strength="high")
    led.add(module="anomaly", claim="dau changed -20% over window", value="-20%",
            source="internal:dau", source_type="internal", strength="high")
    assert ("dau", "region") in _covered_pairs(led)


def test_two_dates_picks_window_endpoints():
    from gaa.core.modules.exploration import _two_dates
    df = _frame([
        {"date": "2026-05-01", "metric": "dau", "value": 1000, "region": "SEA"},
        {"date": "2026-05-04", "metric": "dau", "value": 800, "region": "SEA"},
        {"date": "2026-05-08", "metric": "dau", "value": 400, "region": "SEA"},
    ])
    s, e = _two_dates(df[df["metric"] == "dau"], "2026-05-01", "2026-05-08")
    assert s == pd.Timestamp("2026-05-01") and e == pd.Timestamp("2026-05-08")


def test_two_dates_returns_none_for_single_date():
    from gaa.core.modules.exploration import _two_dates
    df = _frame([{"date": "2026-05-01", "metric": "dau", "value": 1000, "region": "SEA"}])
    s, e = _two_dates(df[df["metric"] == "dau"], None, None)
    assert s is None and e is None


def test_two_dates_falls_back_to_first_last_when_bounds_not_in_data():
    from gaa.core.modules.exploration import _two_dates
    df = _frame([
        {"date": "2026-05-01", "metric": "dau", "value": 1000},
        {"date": "2026-05-08", "metric": "dau", "value": 400},
    ])
    s, e = _two_dates(df[df["metric"] == "dau"], "2026-04-01", "2026-06-01")
    assert s == pd.Timestamp("2026-05-01") and e == pd.Timestamp("2026-05-08")


def test_covered_pairs_excludes_non_segment_modules():
    from gaa.core.modules.exploration import _covered_pairs
    led = EvidenceLedger()
    led.add(module="segment", claim="region=SEA explains 40% of the dau move", value="EP 40%",
            source="internal:dau by region (Adtributor)", source_type="internal", strength="high")
    led.add(module="anomaly", claim="dau changed -20% over window", value="-20%",
            source="internal:dau", source_type="internal", strength="high")
    pairs = _covered_pairs(led)
    assert ("dau", "region") in pairs
    assert len(pairs) == 1  # the anomaly entry must not be counted


def test_p1_finds_mover_in_unqueried_metric():
    from gaa.core.modules.exploration import _p1_surprise_scan
    # queried metric is dau; the *interesting* unprompted move is revenue collapsing in SEA
    rows = []
    for d, (dau_sea, dau_na, rev_sea, rev_na) in {
        "2026-05-01": (1000, 1000, 1000, 1000),
        "2026-05-08": (950, 1000, 100, 1000),
    }.items():
        rows += [
            {"date": d, "metric": "dau", "value": dau_sea, "region": "SEA"},
            {"date": d, "metric": "dau", "value": dau_na, "region": "NA"},
            {"date": d, "metric": "revenue", "value": rev_sea, "region": "SEA"},
            {"date": d, "metric": "revenue", "value": rev_na, "region": "NA"},
        ]
    ctx = _ctx(_frame(rows), metric="dau", start="2026-05-01", end="2026-05-08")
    cands = _p1_surprise_scan(ctx, covered=set())
    joined = " | ".join(c.claim for c in cands)
    assert "revenue" in joined and "SEA" in joined


def test_p1_skips_pairs_already_covered():
    from gaa.core.modules.exploration import _p1_surprise_scan
    rows = []
    for d, (sea, na) in {"2026-05-01": (1000, 1000), "2026-05-08": (400, 1000)}.items():
        rows += [{"date": d, "metric": "dau", "value": sea, "region": "SEA"},
                 {"date": d, "metric": "dau", "value": na, "region": "NA"}]
    ctx = _ctx(_frame(rows), metric="dau", start="2026-05-01", end="2026-05-08")
    cands = _p1_surprise_scan(ctx, covered={("dau", "region")})
    assert all("by region" not in c.source for c in cands)
