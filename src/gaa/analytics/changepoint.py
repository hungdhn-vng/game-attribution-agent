from typing import Optional
import pandas as pd


def detect_changepoint(s: pd.Series) -> Optional[pd.Timestamp]:
    """Date of the single most likely level-shift (Binseg, l2). None if too short/unavailable.

    We force one breakpoint because the agent asks "when did this metric break?" — the best
    single split is the onset. Returns None for series too short to split meaningfully.
    """
    if len(s) < 4:
        return None
    try:
        import ruptures as rpt
        x = s.values.astype(float)
        bkps = rpt.Binseg(model="l2").fit(x).predict(n_bkps=1)
        cps = [b for b in bkps if 0 < b < len(s)]
        return s.index[cps[0]] if cps else None
    except Exception:
        return None


def deviation_z(s: pd.Series) -> Optional[float]:
    """How anomalous the latest point is vs the prior-window baseline (z-score).

    Deseasonalizes via STL only when there's enough history (>=2 weekly cycles); otherwise
    compares the last point to the mean/std of the preceding points. None if too short.
    """
    if len(s) < 3:
        return None
    work = s.astype(float)
    if len(s) >= 14:
        try:
            from statsmodels.tsa.seasonal import STL
            seasonal = STL(work.values, period=7, robust=True).fit().seasonal
            work = pd.Series(work.values - seasonal, index=s.index)
        except Exception:
            pass
    baseline = work.iloc[:-1]
    mean, sd = float(baseline.mean()), float(baseline.std(ddof=0)) or 1.0
    return (float(work.iloc[-1]) - mean) / sd
