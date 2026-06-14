import pandas as pd
import plotly.graph_objects as go

_LK = {"Unlikely": 1, "Possible": 2, "Likely": 3, "Very likely": 4}
_EQ = {"Weak": 1, "Moderate": 2, "Strong": 3}


def timeseries_fig(series: pd.Series, metric: str, start: str, end: str) -> go.Figure:
    fig = go.Figure(go.Scatter(x=list(series.index), y=list(series.values),
                               mode="lines+markers", name=metric))
    fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(title=f"{metric} over time", template="plotly_white",
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
    fig.update_layout(title="You vs the market (indexed to 100)", template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def confidence_matrix_fig(h) -> go.Figure:
    xs, ys, labels = [], [], []
    items = ([(c.claim, c) for c in h.causes.internal]
             + [(c.claim, c) for c in h.causes.market]
             + [(s.description, s) for s in h.scenarios])
    for label, it in items:
        xs.append(_EQ.get(it.evidence_quality, 1))
        ys.append(_LK.get(it.likelihood, 2))
        labels.append(label[:40])
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="markers+text", text=labels,
                               textposition="top center", marker={"size": 14}))
    fig.update_layout(title="Confidence matrix (likelihood × evidence)",
                      xaxis={"tickvals": [1, 2, 3], "ticktext": ["Weak", "Moderate", "Strong"],
                             "title": "Evidence quality", "range": [0.5, 3.5]},
                      yaxis={"tickvals": [1, 2, 3, 4],
                             "ticktext": ["Unlikely", "Possible", "Likely", "Very likely"],
                             "title": "Likelihood", "range": [0.5, 4.5]},
                      template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig
