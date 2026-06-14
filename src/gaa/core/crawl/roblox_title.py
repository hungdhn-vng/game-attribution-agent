"""Resolve a Roblox universe id (often embedded in a CSV key) to its real game title."""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

import httpx

_UNIVERSE_RE = re.compile(r"universe[-_\s]*(\d{5,})", re.IGNORECASE)
_GAMES_URL = "https://games.roblox.com/v1/games?universeIds={id}"


def universe_id_from(text: str) -> Optional[str]:
    m = _UNIVERSE_RE.search(text or "")
    return m.group(1) if m else None


def _default_fetch(url: str) -> str:
    return httpx.get(url, headers={"Accept": "application/json"}, timeout=15.0).text


def lookup_universe_title(universe_id: str,
                          fetch_fn: Optional[Callable[[str], str]] = None) -> Optional[str]:
    fetch = fetch_fn or _default_fetch
    try:
        data = json.loads(fetch(_GAMES_URL.format(id=universe_id)))
        rows = data.get("data") or []
        return rows[0].get("name") if rows else None
    except Exception:
        return None
