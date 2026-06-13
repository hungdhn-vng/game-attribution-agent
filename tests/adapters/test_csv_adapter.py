from pathlib import Path
import pandas as pd
from gaa.core.adapters.csv_adapter import CSVAdapter
from gaa.core.schema.profile import ColumnMapping

SAMPLE = Path("src/gaa/data/sample/generic_metrics.csv")


def _mapping():
    return ColumnMapping(
        date_col="dt",
        metric_cols={"dau_count": "dau", "rev": "revenue"},
        dim_cols={"country": "region", "app_version": "version"},
    )


def test_melts_wide_to_canonical_long():
    df = CSVAdapter().load(str(SAMPLE), _mapping())
    # 6 rows x 2 metrics = 12 canonical rows
    assert len(df) == 12
    assert set(df["metric"].unique()) == {"dau", "revenue"}
    assert {"region", "version"}.issubset(df.columns)


def test_values_and_dims_preserved():
    df = CSVAdapter().load(str(SAMPLE), _mapping())
    row = df[(df["metric"] == "dau") & (df["region"] == "SEA") &
             (df["date"] == pd.Timestamp("2026-05-03"))]
    assert len(row) == 1
    assert row.iloc[0]["value"] == 600.0
    assert row.iloc[0]["version"] == "3.2"


def test_accepts_dataframe_input():
    raw = pd.read_csv(SAMPLE)
    df = CSVAdapter().load(raw, _mapping())
    assert len(df) == 12
