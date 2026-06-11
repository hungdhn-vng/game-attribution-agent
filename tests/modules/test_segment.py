import pandas as pd
from gaa.modules.segment import SegmentDecomposition
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.profile import GameProfile, ColumnMapping


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
