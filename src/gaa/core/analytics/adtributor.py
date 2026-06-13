import math


def _shares(d: dict) -> dict:
    tot = sum(d.values())
    return {k: (v / tot if tot > 0 else 0.0) for k, v in d.items()}


def _xlog2(x: float, m: float) -> float:
    return x * math.log2(x / m) if x > 0 and m > 0 else 0.0


def adtributor_dimension(forecast: dict, actual: dict, teep: float = 0.67) -> dict:
    """Adtributor (Microsoft NSDI'14) for one dimension.

    Returns the elements that best explain the aggregate move, ranked by
    JS-divergence 'surprise', selected until cumulative explanatory power >= teep.
    EP_i = (actual_i - forecast_i) / (A - F); EPs sum to 1 across the dimension.
    """
    keys = set(forecast) | set(actual)
    F = sum(forecast.get(k, 0.0) for k in keys)
    A = sum(actual.get(k, 0.0) for k in keys)
    denom = (A - F) if abs(A - F) > 1e-9 else 1e-9
    P, Q = _shares({k: forecast.get(k, 0.0) for k in keys}), _shares({k: actual.get(k, 0.0) for k in keys})

    rows = []
    for k in keys:
        ep = (actual.get(k, 0.0) - forecast.get(k, 0.0)) / denom
        p, q = P[k], Q[k]
        m = (p + q) / 2
        surprise = 0.5 * (_xlog2(p, m) + _xlog2(q, m))   # JS-divergence term, >= 0
        rows.append({"key": k, "ep": ep, "surprise": surprise})

    rows.sort(key=lambda r: r["surprise"], reverse=True)
    selected, cum = [], 0.0
    for r in rows:
        selected.append(r)
        cum += r["ep"]
        if cum >= teep:
            break
    return {"elements": selected, "surprise": sum(r["surprise"] for r in selected),
            "ep_explained": cum, "size": len(selected)}
