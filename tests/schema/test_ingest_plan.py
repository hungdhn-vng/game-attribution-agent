import pytest
from pydantic import ValidationError
from gaa.core.schema.ingest_plan import ReadSpec, IngestionPlan


def test_wide_plan_valid():
    p = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                      date_col="date", metric_cols={"dau": "dau", "ccu": "ccu"})
    assert p.confidence == 0.0
    assert p.metric_cols["ccu"] == "ccu"


def test_long_plan_valid():
    p = IngestionPlan(read_spec=ReadSpec(format="json"), orientation="long",
                      date_col="day", long_metric_col="kpi", long_value_col="val")
    assert p.long_metric_col == "kpi"


def test_wide_plan_requires_metric_cols():
    with pytest.raises(ValidationError):
        IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide", date_col="date")


def test_long_plan_requires_metric_and_value_cols():
    with pytest.raises(ValidationError):
        IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="long",
                      date_col="date", long_metric_col="kpi")
