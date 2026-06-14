import pandas as pd

from gaa.core.analytics.aggregate import metric_series, RATE_METRICS


def _frame(rows):
    df = pd.DataFrame(rows)
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_prefers_explicit_total_row_over_summing():
    # A rate metric broken down by source, WITH a pre-aggregated 'Total' row.
    df = _frame([
        {"date": "2026-06-03", "metric": "retention_d1", "value": 0.022, "source": "Total"},
        {"date": "2026-06-03", "metric": "retention_d1", "value": 0.014, "source": "Search"},
        {"date": "2026-06-03", "metric": "retention_d1", "value": 0.012, "source": "Friends"},
    ])
    s = metric_series(df, "retention_d1")
    assert s.loc[pd.Timestamp("2026-06-03")] == 0.022  # the Total row, not 0.048 sum


def test_rate_metric_without_total_uses_mean_not_sum():
    df = _frame([
        {"date": "2026-06-03", "metric": "retention_d1", "value": 0.02, "region": "SEA"},
        {"date": "2026-06-03", "metric": "retention_d1", "value": 0.04, "region": "NA"},
    ])
    s = metric_series(df, "retention_d1")
    assert s.loc[pd.Timestamp("2026-06-03")] == 0.03  # mean(0.02, 0.04), not 0.06 sum


def test_additive_metric_without_total_sums():
    df = _frame([
        {"date": "2026-06-03", "metric": "dau", "value": 1000.0, "region": "SEA"},
        {"date": "2026-06-03", "metric": "dau", "value": 800.0, "region": "NA"},
    ])
    s = metric_series(df, "dau")
    assert s.loc[pd.Timestamp("2026-06-03")] == 1800.0  # DAU is additive


def test_missing_metric_returns_empty_series():
    df = _frame([{"date": "2026-06-03", "metric": "retention_d1", "value": 0.02}])
    assert metric_series(df, "retention_d7").empty


def test_retention_metrics_are_rates():
    assert {"retention_d1", "retention_d7", "retention_d30"} <= RATE_METRICS
