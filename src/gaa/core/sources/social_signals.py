"""Perplexity-backed influencer / social-trend signal provider.

Implements the SignalsSource protocol: events(game, genre, start, end) -> list.
Each event is a superset of the legacy {date,title,kind,url,sentiment} shape plus
scope/entity/reach, so CompetitorSignals consumes it unchanged.
"""
from __future__ import annotations

from typing import Callable

from gaa.core.crawl.research import research_json


class SocialSignalProvider:
    def __init__(self, answer_fn: Callable[[str], dict], platform: str = "") -> None:
        self._answer_fn = answer_fn
        self._platform = platform

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        plat = f" on {self._platform}" if self._platform else ""
        game_clause = (f'for the game "{game}" specifically (influencer/YouTuber/TikTok '
                       f'coverage, viral moments), and ' if game else "")
        prompt = (
            f"Between {start} and {end}, what influencer or social-media activity affected "
            f"the {genre!r} game genre{plat}? Look {game_clause}for COMPETING games in this "
            f"genre that gained players or attention in this window and whether an influencer "
            f"drove it (name the game, the influencer/channel, and the date). "
            'Respond ONLY with a JSON object {"signals": [ '
            '{"date": "YYYY-MM-DD", "kind": "influencer"|"social_trend"|"competitor_event", '
            '"scope": "game"|"genre", "entity": str, "reach": str, "url": str, '
            '"summary": str, "sentiment": number between -1 and 1} ]}.'
        )
        data = research_json(self._answer_fn, prompt)
        if not data:
            return []
        out = []
        for s in data.get("signals", []) or []:
            d = s.get("date")
            if not d or not (start <= d <= end):
                continue
            try:
                sentiment = float(s.get("sentiment", 0) or 0)
            except (TypeError, ValueError):
                sentiment = 0.0
            out.append({
                "date": d,
                "kind": s.get("kind", "social_trend"),
                "scope": s.get("scope", "genre"),
                "entity": s.get("entity", ""),
                "reach": s.get("reach", ""),
                "url": s.get("url", ""),
                "summary": s.get("summary", ""),
                "sentiment": sentiment,
                "title": s.get("summary") or s.get("entity") or s.get("kind", "signal"),
            })
        return out
