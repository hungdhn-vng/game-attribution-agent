"""Deterministic migration-hypothesis detector.

Reads the ledger after market + competitor have run. If a game-specific decline
coincides with an influencer/competitor surge near the change-point, it adds a
single derived "likely player migration" entry — with the standing caveat that
user-level migration is unconfirmed without cross-game data.
"""
from __future__ import annotations

from datetime import date

from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger


def _within_days(a: str, b: str, n: int) -> bool:
    try:
        da, db = date.fromisoformat(a[:10]), date.fromisoformat(b[:10])
    except (ValueError, TypeError):
        return False
    return abs((da - db).days) <= n


class MigrationPattern:
    name = "migration"

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        entries = ledger.all()
        game_specific = any(
            e.module == "market"
            and ("underperform" in e.claim.lower() or "internal-driven" in e.claim.lower())
            for e in entries)
        competitor = next(
            (e for e in entries
             if e.module == "competitor" and e.source_type == "external"
             and ("(influencer)" in e.claim or "(competitor_event)" in e.claim)),
            None)
        if not (game_specific and competitor):
            return
        cp = ctx.extras.get("changepoint")
        near = bool(cp and competitor.timeframe and _within_days(competitor.timeframe, cp, 3))
        ledger.add(
            module=self.name,
            claim=("likely player migration — a game-specific decline coincides with an "
                   f"influencer/competitor surge ({competitor.claim[:90]}). "
                   "Caveat: user-level migration unconfirmed without cross-game data."),
            value="timing aligns with change-point" if near else "timing approximate",
            source=competitor.source, source_type="derived",
            strength="med" if near else "low",
            timeframe=f"{ctx.start}..{ctx.end}",
        )
