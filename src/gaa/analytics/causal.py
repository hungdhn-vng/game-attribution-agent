from typing import Optional
import pandas as pd


def causal_counterfactual(target: pd.Series, control: pd.Series,
                          intervention: pd.Timestamp) -> Optional[dict]:
    """Bayesian structural time-series counterfactual (CausalImpact-style) on statsmodels.

    Fit target ~ local-level + control on the PRE period, forecast the counterfactual
    over POST using the control, and report the cumulative effect (actual - counterfactual)
    with a 95% interval. Returns None if there is too little history to fit.
    """
    df = pd.concat([target.rename("y"), control.rename("x")], axis=1).dropna().sort_index()
    pre, post = df[df.index < intervention], df[df.index >= intervention]
    if len(pre) < 5 or len(post) < 1:
        return None
    from statsmodels.tsa.statespace.structural import UnobservedComponents
    model = UnobservedComponents(pre["y"].values, level="local level", exog=pre[["x"]].values)
    res = model.fit(disp=False)
    fc = res.get_forecast(steps=len(post), exog=post[["x"]].values)
    ci = fc.conf_int(alpha=0.05)            # columns: [lower, upper]
    actual = float(post["y"].sum())
    counterfactual = float(fc.predicted_mean.sum())
    effect = actual - counterfactual
    lower = actual - float(ci[:, 1].sum())  # cumulative effect lower bound
    upper = actual - float(ci[:, 0].sum())
    return {"effect": effect, "rel": effect / counterfactual if counterfactual else 0.0,
            "lower": lower, "upper": upper, "significant": not (lower <= 0 <= upper),
            "counterfactual": counterfactual, "actual": actual}
