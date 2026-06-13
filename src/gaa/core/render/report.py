import os
import pandas as pd
import plotly.io as pio
import plotly.offline as pyo
from jinja2 import Environment, FileSystemLoader, select_autoescape
from gaa.core.schema.hypothesis import AttributionHypothesis
from gaa.core.render.charts import timeseries_fig, overlay_fig, confidence_matrix_fig

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES),
                   autoescape=select_autoescape(["html"]))


def _div(fig) -> str:
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       default_width="100%", default_height="380px")


def render_report(h: AttributionHypothesis, metric: str, start: str, end: str,
                  series: pd.Series, genre_trend: dict) -> str:
    charts = {
        "timeseries": _div(timeseries_fig(series, metric, start, end)),
        "overlay": _div(overlay_fig(series, genre_trend, metric)),
        "matrix": _div(confidence_matrix_fig(h)),
    }
    return _env.get_template("report.html.j2").render(
        h=h, charts=charts, plotlyjs=pyo.get_plotlyjs())
