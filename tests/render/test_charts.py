import pandas as pd
import plotly.graph_objects as go
from gaa.core.render.charts import timeseries_fig, overlay_fig, confidence_matrix_fig
from gaa.core.schema.hypothesis import AttributionHypothesis, Cause, Causes
from gaa.core.schema.confidence import Confidence


def test_timeseries_fig_has_trace():
    s = pd.Series([100.0, 90.0, 60.0],
                  index=pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]))
    fig = timeseries_fig(s, "dau", "2026-05-01", "2026-05-03")
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1


def test_overlay_indexes_both_series():
    game = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    genre = {"2026-05-01": 100.0, "2026-05-03": 98.0}
    fig = overlay_fig(game, genre, "dau")
    assert len(fig.data) == 2  # game + genre


def test_confidence_matrix_plots_each_claim():
    h = AttributionHypothesis(
        main_story="x", confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="a", evidence_ids=["L1"], likelihood="Likely",
                                       evidence_quality="Strong")]))
    fig = confidence_matrix_fig(h)
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1
