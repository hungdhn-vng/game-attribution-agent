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


def test_confidence_matrix_fans_out_collocated_points():
    # Two causes that share the same likelihood + evidence cell must not stack.
    h = AttributionHypothesis(
        main_story="x", confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[
            Cause(claim="cause one", evidence_ids=["L1"], likelihood="Likely", evidence_quality="Strong"),
            Cause(claim="cause two", evidence_ids=["L2"], likelihood="Likely", evidence_quality="Strong")]))
    fig = confidence_matrix_fig(h)
    xs = list(fig.data[0].x)
    assert len(xs) == 2
    assert xs[0] != xs[1]  # fanned apart, not stacked on the same point


def test_charts_have_transparent_backgrounds():
    s = pd.Series([100.0, 90.0, 60.0],
                  index=pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]))
    genre = {"2026-05-01": 100.0, "2026-05-03": 98.0}
    h = AttributionHypothesis(
        main_story="x", confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="a", evidence_ids=["L1"], likelihood="Likely",
                                       evidence_quality="Strong")]))
    figs = [timeseries_fig(s, "dau", "2026-05-01", "2026-05-03"),
            overlay_fig(s, genre, "dau"),
            confidence_matrix_fig(h)]
    for fig in figs:
        assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
        assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"


def test_charts_use_dossier_sans_font():
    s = pd.Series([100.0, 90.0, 60.0],
                  index=pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]))
    genre = {"2026-05-01": 100.0, "2026-05-03": 98.0}
    h = AttributionHypothesis(
        main_story="x", confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="a", evidence_ids=["L1"], likelihood="Likely",
                                       evidence_quality="Strong")]))
    figs = [timeseries_fig(s, "dau", "2026-05-01", "2026-05-03"),
            overlay_fig(s, genre, "dau"),
            confidence_matrix_fig(h)]
    for fig in figs:
        assert "Geist" in fig.layout.font.family
