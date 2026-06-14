import textwrap

import pandas as pd
import plotly.graph_objects as go

_LK = {"Unlikely": 1, "Possible": 2, "Likely": 3, "Very likely": 4}
_EQ = {"Weak": 1, "Moderate": 2, "Strong": 3}

# Match the dossier's sans stack (report.html.j2) so charts read as part of the report.
_FONT = {"family": 'Geist, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
         "size": 12}


def timeseries_fig(series: pd.Series, metric: str, start: str, end: str) -> go.Figure:
    fig = go.Figure(go.Scatter(x=list(series.index), y=list(series.values),
                               mode="lines+markers", name=metric))
    fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(title=f"{metric} over time", template="plotly_white", font=_FONT,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def overlay_fig(game: pd.Series, genre: dict, metric: str) -> go.Figure:
    g = game.sort_index()
    base = g.iloc[0] if len(g) and g.iloc[0] else 1.0
    game_idx = (g / base) * 100.0
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[str(d.date()) for d in game_idx.index],
                             y=list(game_idx.values), mode="lines+markers",
                             name=f"Your {metric} (indexed)"))
    if genre:
        ks = sorted(genre)
        fig.add_trace(go.Scatter(x=ks, y=[genre[k] for k in ks],
                                 mode="lines+markers", name="Genre (indexed)"))
    fig.update_layout(title="You vs the market (indexed to 100)", template="plotly_white", font=_FONT,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


_CAT_COLOR = {"internal": "#3b82f6", "market": "#f59e0b", "scenario": "#9ca3af"}


def _wrap_hover(text: str, width: int = 42) -> str:
    """Plotly draws hovertext on a single line; insert <br> on word boundaries
    so long claims wrap inside the chart instead of overflowing its width."""
    return "<br>".join(textwrap.wrap(text, width=width)) or text


def confidence_matrix_fig(h) -> go.Figure:
    items = ([("internal", c.claim, c) for c in h.causes.internal]
             + [("market", c.claim, c) for c in h.causes.market]
             + [("scenario", s.description, s) for s in h.scenarios])
    # The grid is discrete (3 evidence levels x 4 likelihood levels), so several
    # items routinely land on the same cell. Bucket by cell, then fan co-located
    # points out horizontally and stagger their labels so nothing overlaps.
    coords, cells = [], {}
    for kind, label, it in items:
        x = _EQ.get(it.evidence_quality, 1)
        y = _LK.get(it.likelihood, 2)
        coords.append((kind, label, x, y))
        cells.setdefault((x, y), []).append(len(coords) - 1)

    xs, ys, texts, hovers, colors, positions = [], [], [], [], [], []
    for idxs in cells.values():
        n = len(idxs)
        for j, i in enumerate(idxs):
            kind, label, x, y = coords[i]
            xs.append(x + (j - (n - 1) / 2) * 0.18)
            ys.append(y)
            texts.append(label if len(label) <= 22 else label[:21] + "…")
            hovers.append(_wrap_hover(label))
            colors.append(_CAT_COLOR[kind])
            positions.append("top center" if j % 2 == 0 else "bottom center")

    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=texts, textposition=positions,
        hovertext=hovers, hoverinfo="text", cliponaxis=False,
        textfont={"size": 10}, marker={"size": 13, "color": colors}))
    fig.update_layout(title="Confidence matrix (likelihood × evidence)",
                      showlegend=False,
                      xaxis={"tickvals": [1, 2, 3], "ticktext": ["Weak", "Moderate", "Strong"],
                             "title": "Evidence quality", "range": [0.4, 3.6]},
                      yaxis={"tickvals": [1, 2, 3, 4],
                             "ticktext": ["Unlikely", "Possible", "Likely", "Very likely"],
                             "title": "Likelihood", "range": [0.4, 4.6]},
                      template="plotly_white", font=_FONT,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig
