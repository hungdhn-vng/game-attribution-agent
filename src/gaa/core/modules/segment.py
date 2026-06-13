import pandas as pd
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.analytics.adtributor import adtributor_dimension

DIMS = ["version", "region", "platform", "cohort", "device", "source"]


class SegmentDecomposition:
    name = "segment"

    def __init__(self, dims: list | None = None) -> None:
        self._dims = dims or DIMS

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.metric and ctx.start and ctx.end):
            return
        df = ctx.metrics[ctx.metrics["metric"] == ctx.metric]
        start, end = pd.Timestamp(ctx.start), pd.Timestamp(ctx.end)

        best = None  # (dim, adtributor-result)
        for dim in self._dims:
            if dim not in df.columns or df[dim].isna().all():
                continue
            forecast = df[df["date"] == start].groupby(dim)["value"].sum().to_dict()
            actual = df[df["date"] == end].groupby(dim)["value"].sum().to_dict()
            if not forecast or not actual:
                continue
            res = adtributor_dimension(forecast, actual)
            if best is None or res["surprise"] > best[1]["surprise"]:
                best = (dim, res)

        if best is None:
            ledger.add(module=self.name, claim="no segment dimensions to decompose",
                       value="n/a", source="internal", source_type="derived", strength="low")
            return

        dim, res = best
        for el in res["elements"]:
            ep = el["ep"]
            strength = "high" if abs(ep) >= 0.5 else ("med" if abs(ep) >= 0.2 else "low")
            ledger.add(
                module=self.name,
                claim=f"{dim}={el['key']} explains {ep*100:.0f}% of the {ctx.metric} move",
                value=f"EP {ep*100:.0f}% · surprise {el['surprise']:.3f}",
                source=f"internal:{ctx.metric} by {dim} (Adtributor)",
                source_type="internal",
                strength=strength,
                timeframe=f"{ctx.start}..{ctx.end}",
            )
