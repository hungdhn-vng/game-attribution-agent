from gaa.core.onboarding.profiler import Profiler
from gaa.core.llm.client import FakeLLM
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
import pandas as pd


def _raw():
    df = pd.DataFrame({"dt": ["2026-05-01"], "dau_count": [100], "ccu": [20],
                       "country": ["SEA"]})
    return RawTable(df=df, read_spec=ReadSpec(format="csv", delimiter=","))


def test_propose_returns_wide_plan_with_passthrough():
    preset = {"orientation": "wide", "date_col": "dt",
              "metric_cols": {"dau_count": "dau", "ccu": "ccu"},
              "dim_cols": {"country": "region"}, "confidence": 0.9, "notes": []}
    plan = Profiler(FakeLLM(preset)).propose(_raw())
    assert isinstance(plan, IngestionPlan)
    assert plan.read_spec.format == "csv"          # read_spec comes from the RawTable
    assert plan.metric_cols["ccu"] == "ccu"        # passthrough metric kept
    assert plan.confidence == 0.9


def test_summary_mentions_format_and_mappings():
    plan = IngestionPlan(read_spec=ReadSpec(format="excel"), orientation="wide",
                         date_col="dt", metric_cols={"dau_count": "dau"},
                         dim_cols={"country": "region"}, confidence=0.5)
    preview = pd.DataFrame({"date": ["2026-05-01"], "metric": ["dau"], "value": [100.0]})
    msg = Profiler(FakeLLM({})).summary(plan, preview)
    assert "excel" in msg and "dt" in msg and "dau" in msg and "50%" in msg
