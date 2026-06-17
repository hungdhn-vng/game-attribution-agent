import pandas as pd
import pytest
from gaa.core.adapters.plan_adapter import PlanAdapter
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
from gaa.core.ingest.detect import IngestError


def _wide_df():
    return pd.DataFrame({
        "date": ["2026-05-01", "2026-05-01"],
        "platform": ["ios", "android"],
        "game_mode": ["ranked", "casual"],
        "dau": ["1,000", "1500"],     # thousands separator must be coerced
        "ccu": [200, 280],
    })


def test_wide_preserves_passthrough_metric_and_dim():
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"dau": "dau", "ccu": "ccu"},
                         dim_cols={"platform": "platform", "game_mode": "game_mode"})
    out = PlanAdapter().load(_wide_df(), plan)
    assert set(out["metric"].unique()) == {"dau", "ccu"}        # ccu kept, not dropped
    assert "game_mode" in out.columns                            # custom dim kept
    dau_ios = out[(out["metric"] == "dau") & (out["platform"] == "ios")]
    assert dau_ios.iloc[0]["value"] == 1000.0                    # "1,000" → 1000.0


def test_long_orientation():
    df = pd.DataFrame({"day": ["2026-05-01", "2026-05-01"],
                       "kpi": ["dau", "revenue"], "val": [1000, 500],
                       "country": ["SEA", "SEA"]})
    plan = IngestionPlan(read_spec=ReadSpec(format="json"), orientation="long",
                         date_col="day", long_metric_col="kpi", long_value_col="val",
                         dim_cols={"country": "region"})
    out = PlanAdapter().load(df, plan)
    assert set(out["metric"].unique()) == {"dau", "revenue"}
    assert out[out["metric"] == "revenue"].iloc[0]["region"] == "SEA"


def test_currency_and_percent_coercion():
    df = pd.DataFrame({"date": ["2026-05-01"], "revenue": ["$1,234"], "ret": ["45%"]})
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"revenue": "revenue", "ret": "retention_d1"})
    out = PlanAdapter().load(df, plan)
    assert out[out["metric"] == "revenue"].iloc[0]["value"] == 1234.0
    assert out[out["metric"] == "retention_d1"].iloc[0]["value"] == 45.0


def test_missing_column_raises_plan_mismatch():
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"nope": "dau"})
    with pytest.raises(IngestError) as e:
        PlanAdapter().load(pd.DataFrame({"date": ["2026-05-01"], "dau": [1]}), plan)
    assert e.value.code == "plan_mismatch"


def test_all_non_numeric_raises_bad_values():
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"dau": "dau"})
    with pytest.raises(IngestError) as e:
        PlanAdapter().load(pd.DataFrame({"date": ["2026-05-01"], "dau": ["n/a"]}), plan)
    assert e.value.code == "bad_values"
