import pandas as pd
from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.base import BenchmarkSource
from gaa.analytics.causal import causal_counterfactual


class MarketBenchmark:
    name = "market"

    def __init__(self, source: BenchmarkSource) -> None:
        self._source = source

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.metric and ctx.start and ctx.end):
            return
        try:
            trend = self._source.genre_trend(ctx.profile.genre, ctx.start, ctx.end)
        except Exception as exc:  # graceful degradation — a failing feed is a data gap, not a crash
            ledger.add(module=self.name,
                       claim=f"market benchmark unavailable ({type(exc).__name__})",
                       value="n/a", source="benchmark", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        if len(trend) < 2:
            ledger.add(module=self.name, claim="no genre benchmark available for this window",
                       value="n/a", source="benchmark", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            # Try qualitative context if the source exposes it
            ctx_q = getattr(self._source, "qualitative_context", lambda *_: None)(ctx.profile.genre)
            if ctx_q:
                cite = ctx_q.get("citations") or []
                ledger.add(module=self.name,
                    claim=f"market context: genre trending {ctx_q.get('direction','?')} — {ctx_q.get('summary','')}",
                    value=ctx_q.get("direction","?"),
                    source=(cite[0].get("url") if cite else "web-search"),
                    source_type="external", strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return

        control = pd.Series({pd.Timestamp(d): v for d, v in trend.items()}).sort_index()
        target = (ctx.metrics[ctx.metrics["metric"] == ctx.metric]
                  .groupby("date")["value"].sum().sort_index())
        intervention = pd.Timestamp(ctx.extras.get("changepoint") or ctx.start)
        result = causal_counterfactual(target, control, intervention)

        if result is None:
            # fallback: indexed comparison of % change (game vs genre)
            keys = sorted(trend)
            genre_change = (trend[keys[-1]] - trend[keys[0]]) / abs(trend[keys[0]])
            gchange = ((target.iloc[-1] - target.iloc[0]) / abs(target.iloc[0])
                       if len(target) >= 2 and target.iloc[0] else 0.0)
            verdict = ("underperforming the genre" if gchange - genre_change < -0.05
                       else "in line with the genre")
            ledger.add(module=self.name,
                       claim=f"genre {genre_change:+.0%} vs game {gchange:+.0%} → {verdict} (indexed)",
                       value=f"genre {genre_change:+.2%}; game {gchange:+.2%}",
                       source="benchmark:genre_index", source_type="external", strength="med",
                       timeframe=f"{ctx.start}..{ctx.end}")
            return

        rel = result["rel"]
        verdict = ("internal-driven (beyond the market)" if result["significant"] and rel < -0.05
                   else "market-wide" if abs(rel) <= 0.05 else "partly internal")
        ledger.add(
            module=self.name,
            claim=f"after absorbing the market, {ctx.metric} is {rel:+.0%} vs its counterfactual → {verdict}",
            value=f"effect {result['effect']:+.0f} (95% CI {result['lower']:+.0f}..{result['upper']:+.0f})",
            source="causalimpact:genre-control", source_type="derived",
            strength="high" if result["significant"] else "med",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
