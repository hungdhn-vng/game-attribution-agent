import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.analytics.changepoint import detect_changepoint, deviation_z


def _series(df: pd.DataFrame, metric: str) -> pd.Series:
    return df[df["metric"] == metric].groupby("date")["value"].sum().sort_index()


def _pct(s: pd.Series) -> float:
    return (s.iloc[-1] - s.iloc[0]) / abs(s.iloc[0]) if len(s) >= 2 and s.iloc[0] else 0.0


def _salience(s: pd.Series) -> float:
    """How notable a movement is — by statistical significance (|z| vs the series' own
    variability), NOT raw % change. Raw % change over-selects volatile rate / small-base
    metrics; z is comparable across metric types. Falls back to |%change| when z is undefined
    (series too short)."""
    z = deviation_z(s)
    return abs(z) if z is not None else abs(_pct(s))


class AnomalyDetection:
    name = "anomaly"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        metrics = list(ctx.metrics["metric"].unique())
        if not metrics:
            ledger.add(module=self.name, claim="no internal metrics available", value="n/a",
                       source="internal", source_type="derived", strength="low")
            return

        # scan mode: surface the most STATISTICALLY ANOMALOUS metric, not the largest % swing
        target = ctx.metric or max(metrics, key=lambda m: _salience(_series(ctx.metrics, m)))
        ctx.metric = target
        s = _series(ctx.metrics, target)
        change = _pct(s)
        ctx.direction = "down" if change < 0 else "up"
        ctx.start = ctx.start or str(s.index.min().date())
        ctx.end = ctx.end or str(s.index.max().date())

        onset = detect_changepoint(s)
        if onset is not None:
            ctx.extras["changepoint"] = str(onset.date())   # feeds Market module's intervention
        z = deviation_z(s)

        claim = f"{target} changed {change:+.0%} over window"
        if onset is not None:
            claim += f", breaking around {onset.date()}"
        value = f"{change:+.2%}" + (f" · z={z:+.1f}" if z is not None else "")
        # strength reflects significance: a big % move within ~1σ is noise, not high-confidence
        if z is not None:
            strength = "high" if abs(z) >= 2 else ("med" if abs(z) >= 1 else "low")
        else:
            strength = "high" if abs(change) >= 0.2 else "med"
        ledger.add(module=self.name, claim=claim, value=value, source=f"internal:{target}",
                   source_type="internal", strength=strength, timeframe=f"{ctx.start}..{ctx.end}")
