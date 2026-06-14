"""Collapse a canonical long-frame to one value per date for a metric.

Two correctness rules that the naive ``groupby(date).sum()`` violated:

* **Prefer an explicit pre-aggregated row.** Roblox-style exports include a
  ``Total`` row alongside the per-segment breakdown (e.g. ``source`` =
  Total/Search/Friends/...). Summing every row double-counts — the headline must
  follow the ``Total`` row when one exists.
* **Don't sum rate metrics.** Retention and ARPPU are ratios; summing them across
  segments is meaningless. Combine with a mean instead; sum only additive metrics.
"""
from __future__ import annotations

import pandas as pd

from gaa.core.schema.canonical import CANONICAL_DIMS

# Ratio / average metrics — NOT additive across segments.
RATE_METRICS = {"retention_d1", "retention_d7", "retention_d30", "arppu"}

# Labels a data source uses for a pre-aggregated "all segments" row.
AGGREGATE_LABELS = {"total", "all", "overall", "grand total", "all users", "all sources"}


def is_aggregate_label(series: pd.Series) -> pd.Series:
    """Boolean mask: which rows carry a pre-aggregated label (e.g. 'Total')."""
    return series.notna() & series.astype("string").str.strip().str.lower().isin(AGGREGATE_LABELS)


def metric_series(df: pd.DataFrame, metric: str) -> pd.Series:
    """One value per date for ``metric`` (sorted by date). Empty if absent."""
    sub = df[df["metric"] == metric]
    if sub.empty:
        return pd.Series(dtype="float64")
    # Prefer an explicit pre-aggregated row on whichever dimension carries one.
    for dim in CANONICAL_DIMS:
        if dim in sub.columns and sub[dim].notna().any():
            mask = is_aggregate_label(sub[dim])
            if mask.any():
                return sub[mask].groupby("date")["value"].mean().sort_index()
    how = "mean" if metric in RATE_METRICS else "sum"
    grouped = sub.groupby("date")["value"]
    return (grouped.mean() if how == "mean" else grouped.sum()).sort_index()
