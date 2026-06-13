import pandas as pd
from gaa.core.onboarding.profiler import Profiler
from gaa.core.llm.client import FakeLLM
from gaa.core.schema.profile import ColumnMapping


def test_propose_mapping_from_sample():
    sample = pd.DataFrame({"dt": ["2026-05-01"], "dau_count": [100],
                           "rev": [50.0], "country": ["SEA"]})
    preset = {"date_col": "dt",
              "metric_cols": {"dau_count": "dau", "rev": "revenue"},
              "dim_cols": {"country": "region"}}
    m = Profiler(FakeLLM(preset)).propose(sample)
    assert isinstance(m, ColumnMapping)
    assert m.date_col == "dt"
    assert m.metric_cols["rev"] == "revenue"


def test_confirmation_message_lists_mapping():
    m = ColumnMapping(date_col="dt", metric_cols={"dau_count": "dau"}, dim_cols={})
    msg = Profiler(FakeLLM({})).confirmation_message(m)
    assert "dt" in msg and "dau" in msg
