import pandas as pd
from gaa.core.modules.segment import SegmentDecomposition
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _ctx():
    rows = []
    for d, sea, na in [("2026-05-01", 1000, 800), ("2026-05-03", 400, 770)]:
        rows += [{"date": d, "metric": "dau", "value": float(sea), "region": "SEA"},
                 {"date": d, "metric": "dau", "value": float(na), "region": "NA"}]
    df = pd.DataFrame(rows)
    for c in ["platform", "version", "cohort", "device", "source"]:
        df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    prof = GameProfile(name="G", platform="roblox", genre="survival",
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-05-01", end="2026-05-03", direction="down")


def test_attributes_with_citable_percentage():
    led = EvidenceLedger()
    SegmentDecomposition().run(_ctx(), led)
    entries = [e for e in led.all() if e.module == "segment"]
    assert entries and entries[0].source_type == "internal"
    joined = " ".join(e.claim for e in entries)
    assert "SEA" in joined and "%" in joined        # % contribution is cited
    assert "Adtributor" in entries[0].source


def test_dims_filter_restricts_to_one_dimension():
    import pandas as pd
    from gaa.core.modules.segment import SegmentDecomposition
    from gaa.core.modules.base import AnalysisContext
    from gaa.core.schema.ledger import EvidenceLedger
    from gaa.core.schema.profile import GameProfile, ColumnMapping

    rows = []
    for d, (sea, na, v1, v2) in {
        "2026-05-01": (1000, 800, 900, 900),
        "2026-05-03": (400, 770, 300, 870),
    }.items():
        rows += [
            {"date": d, "metric": "dau", "value": sea, "region": "SEA", "version": "1.0"},
            {"date": d, "metric": "dau", "value": na, "region": "NA", "version": "1.0"},
        ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["platform", "cohort", "device", "source"]:
        df[col] = None
    profile = GameProfile(name="G", platform="roblox", genre="survival",
                          mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}))
    ctx = AnalysisContext(profile=profile, metrics=df, query="q", metric="dau",
                          start="2026-05-01", end="2026-05-03", direction="down")
    ledger = EvidenceLedger()
    SegmentDecomposition(dims=["region"]).run(ctx, ledger)
    claims = [e.claim for e in ledger.all()]
    assert claims, "expected at least one segment entry"
    assert all("region=" in c or "no segment" in c for c in claims)
    assert not any("version=" in c for c in claims)


def _source_ctx_via_canonical(include_total: bool):
    """A retention-by-source frame ingested through the canonical boundary
    (tz-aware 'Z' dates), exactly like a Roblox 'Top Sources' export."""
    from gaa.core.schema.canonical import validate_canonical
    rows = []
    series = {"Search": (0.014, 0.022), "Friends": (0.012, 0.020),
              "Home Recommendation": (0.028, 0.055)}
    if include_total:
        series["Total"] = (0.022, 0.034)
    for src, (a, b) in series.items():
        rows += [{"date": "2026-06-03T00:00:00.000Z", "metric": "retention_d1", "value": a, "source": src},
                 {"date": "2026-06-08T00:00:00.000Z", "metric": "retention_d1", "value": b, "source": src}]
    df = validate_canonical(pd.DataFrame(rows))
    prof = GameProfile(name="G", platform="Custom", genre="shopping",
                       mapping=ColumnMapping(date_col="Date",
                                             metric_cols={"x": "retention_d1"},
                                             dim_cols={"Top Sources": "source"}))
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="retention_d1",
                           start="2026-06-03", end="2026-06-08", direction="up")


def test_finds_source_dimension_on_tz_aware_dates():
    # The reported bug: a populated 'source' dim was reported as "no dimensions"
    # because tz-aware dates never matched the tz-naive start/end timestamps.
    led = EvidenceLedger()
    SegmentDecomposition().run(_source_ctx_via_canonical(include_total=True), led)
    claims = [e.claim for e in led.all() if e.module == "segment"]
    assert any("source=" in c for c in claims), f"expected a source decomposition, got {claims}"
    assert not any("no segment dimensions" in c for c in claims)


def test_excludes_aggregate_total_row_from_decomposition():
    led = EvidenceLedger()
    SegmentDecomposition(dims=["source"]).run(_source_ctx_via_canonical(include_total=True), led)
    claims = [e.claim for e in led.all() if e.module == "segment"]
    assert any("source=" in c for c in claims)
    assert not any("source=Total" in c for c in claims), \
        "the pre-aggregated 'Total' row must not be decomposed as a peer channel"


def test_segment_decomposes_a_custom_dimension():
    from gaa.core.modules.segment import SegmentDecomposition
    from gaa.core.modules.base import AnalysisContext
    from gaa.core.schema.ledger import EvidenceLedger
    rows = []
    for mode, (v0, v1) in {"ranked": (100, 50), "casual": (100, 100)}.items():
        rows.append({"date": "2026-05-01", "metric": "dau", "value": float(v0), "game_mode": mode})
        rows.append({"date": "2026-05-10", "metric": "dau", "value": float(v1), "game_mode": mode})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    ctx = AnalysisContext(profile=None, metrics=df, query="q", metric="dau",
                          start="2026-05-01", end="2026-05-10")
    led = EvidenceLedger()
    SegmentDecomposition().run(ctx, led)
    claims = " ".join(e.claim for e in led.all())
    assert "game_mode=ranked" in claims
