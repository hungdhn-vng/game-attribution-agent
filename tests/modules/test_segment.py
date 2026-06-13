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
