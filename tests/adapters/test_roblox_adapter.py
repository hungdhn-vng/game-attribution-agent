from pathlib import Path
import pandas as pd
from gaa.core.adapters.roblox_adapter import RobloxAdapter, DEFAULT_ROBLOX_MAPPING

SAMPLE = Path("src/gaa/data/sample/roblox_export.csv")


def test_default_mapping_covers_core_metrics():
    canon_metrics = set(DEFAULT_ROBLOX_MAPPING.metric_cols.values())
    assert {"dau", "retention_d1", "retention_d7", "revenue"} <= canon_metrics


def test_loads_with_default_mapping():
    df = RobloxAdapter().load(str(SAMPLE))
    assert set(df["metric"].unique()) >= {"dau", "retention_d7", "revenue"}
    row = df[(df["metric"] == "dau") & (df["platform"] == "Mobile") &
             (df["date"] == pd.Timestamp("2026-05-03"))]
    assert row.iloc[0]["value"] == 9000.0


def test_load_accepts_override_mapping():
    from gaa.core.schema.profile import ColumnMapping
    m = ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={"Country": "region"})
    df = RobloxAdapter().load(str(SAMPLE), m)
    assert set(df["metric"].unique()) == {"dau"}
