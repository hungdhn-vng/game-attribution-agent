from gaa.modules.base import AnalysisContext
from gaa.schema.ledger import EvidenceLedger
from gaa.sources.base import SignalsSource

_STRENGTH_BY_KIND = {"patch": "high", "competitor": "med", "news": "med", "social": "low"}


class CompetitorSignals:
    name = "competitor"

    def __init__(self, source: SignalsSource) -> None:
        self._source = source

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.start and ctx.end):
            return
        events = self._source.events(ctx.profile.name, ctx.profile.genre, ctx.start, ctx.end)
        if not events:
            ledger.add(module=self.name,
                       claim="no external competitor/event signals found in window",
                       value="0 events", source="signals", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        for ev in events:
            ledger.add(
                module=self.name,
                claim=f"{ev['kind']}: {ev['title']}",
                value=f"sentiment {ev.get('sentiment', 0):+.2f}",
                source=ev.get("url", "signals"),
                source_type="external",
                strength=_STRENGTH_BY_KIND.get(ev["kind"], "low"),
                timeframe=ev["date"],
            )
