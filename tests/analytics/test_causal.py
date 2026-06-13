import pandas as pd
from gaa.analytics.causal import causal_counterfactual


def _series(vals, start="2026-04-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D")
    return pd.Series(vals, index=idx)


def test_detects_internal_drop_when_control_holds():
    # 14 pre days target≈control≈100; then target drops to 60 while control holds 100
    pre = [100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 100, 101, 99, 100]
    ctrl = [100] * 14
    target = _series(pre + [60, 61, 59])
    control = _series(ctrl + [100, 100, 100])
    res = causal_counterfactual(target, control, pd.Timestamp("2026-04-15"))
    assert res is not None
    assert res["rel"] < -0.2          # large negative effect vs counterfactual
    assert res["significant"] is True  # CI excludes zero


def test_returns_none_when_insufficient_history():
    assert causal_counterfactual(_series([100, 60]), _series([100, 100]),
                                 pd.Timestamp("2026-04-02")) is None
