import pandas as pd
from gaa.core.render.report import render_report
from gaa.core.schema.hypothesis import AttributionHypothesis, Cause, Causes
from gaa.core.schema.confidence import Confidence


def _hyp():
    return AttributionHypothesis(
        main_story="Mostly internal — SEA fell.",
        confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="SEA collapse", evidence_ids=["L1"],
                                       likelihood="Likely", evidence_quality="Strong")]),
        assumptions_and_gaps=["no UA data"])


def test_report_is_self_contained_html():
    series = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    html = render_report(_hyp(), metric="dau", start="2026-05-01", end="2026-05-03",
                         series=series, genre_trend={"2026-05-01": 100.0, "2026-05-03": 98.0})
    assert "<html" in html.lower()
    assert "Mostly internal" in html
    assert "Plotly" in html          # inline plotly.js present
    assert "no UA data" in html      # gaps shown
    assert "Confidence matrix" in html


def test_report_charts_have_stable_ids():
    series = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    html = render_report(_hyp(), metric="dau", start="2026-05-01", end="2026-05-03",
                         series=series, genre_trend={"2026-05-01": 100.0, "2026-05-03": 98.0})
    assert "gaa-chart-timeseries" in html
    assert "gaa-chart-overlay" in html
    assert "gaa-chart-matrix" in html


def test_report_supports_light_dark_theme():
    series = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    html = render_report(_hyp(), metric="dau", start="2026-05-01", end="2026-05-03",
                         series=series, genre_trend={"2026-05-01": 100.0, "2026-05-03": 98.0})
    assert "data-theme" in html                 # themed document root
    assert '[data-theme="dark"]' in html        # dark-mode token block
    assert "gaa-theme" in html                  # parent -> iframe message type
    assert "gaa-theme-ready" in html            # iframe -> parent handshake
