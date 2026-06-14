from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.sources.base import SignalsSource

_STRENGTH_BY_KIND = {"patch": "high", "competitor": "med", "competitor_event": "med",
                     "news": "med", "influencer": "med", "social": "low", "social_trend": "low"}


class CompetitorSignals:
    name = "competitor"

    def __init__(self, source: SignalsSource) -> None:
        self._source = source

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not (ctx.start and ctx.end):
            return
        game = getattr(ctx.profile, "title", None) or ctx.profile.name
        try:
            events = self._source.events(game, ctx.profile.genre, ctx.start, ctx.end)
        except Exception as exc:  # graceful degradation — a failing feed is a data gap, not a crash
            ledger.add(module=self.name, claim=f"signal feed unavailable ({type(exc).__name__})",
                       value="n/a", source="signals", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        if not events:
            ledger.add(module=self.name, claim="no external competitor/event signals found in window",
                       value="0 events", source="signals", source_type="derived",
                       strength="low", timeframe=f"{ctx.start}..{ctx.end}")
            return
        for ev in events:
            kind = ev.get("kind", "social")
            scope = ev.get("scope")
            if scope == "game":
                claim = (f"external ({kind}): {ev.get('entity', '')} on {ev['date']} "
                         f"(reach {ev.get('reach', '?')}) — may explain the "
                         f"{ctx.metric or 'metric'} move: {ev.get('title', '')}")
                strength = ("high" if kind in ("influencer", "competitor_event") and ev.get("reach")
                            else _STRENGTH_BY_KIND.get(kind, "low"))
            elif scope == "genre":
                claim = f"genre social trend ({kind}): {ev.get('title', '')}"
                strength = _STRENGTH_BY_KIND.get(kind, "low")
            else:
                claim = f"{kind}: {ev['title']}"  # legacy shape, unchanged
                strength = _STRENGTH_BY_KIND.get(kind, "low")
            ledger.add(module=self.name, claim=claim,
                       value=f"sentiment {ev.get('sentiment', 0):+.2f}",
                       source=ev.get("url", "signals"), source_type="external",
                       strength=strength, timeframe=ev["date"])
