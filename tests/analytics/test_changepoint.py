import pandas as pd
from gaa.core.analytics.changepoint import detect_changepoint, deviation_z


def _s(vals, start="2026-04-01"):
    return pd.Series([float(v) for v in vals], index=pd.date_range(start, periods=len(vals), freq="D"))


def test_changepoint_finds_the_break():
    s = _s([100] * 8 + [60] * 8)
    cp = detect_changepoint(s)
    assert cp is not None
    assert pd.Timestamp("2026-04-07") <= cp <= pd.Timestamp("2026-04-11")


def test_changepoint_none_on_short_series():
    assert detect_changepoint(_s([100, 60])) is None


def test_deviation_z_flags_a_spike():
    z = deviation_z(_s([100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 60]))
    assert z is not None and abs(z) >= 2
