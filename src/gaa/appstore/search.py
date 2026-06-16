"""Public App Store (iTunes Search API) discovery — name/genre → candidate apps + their App Store
trackId (== Sensor Tower iOS app_id). Server-side: the runtime can reach Apple directly (no auth,
no origin allowlist), so this never needs the browser-proxy used by the st_* data tools."""
from __future__ import annotations

import httpx

_URL = "https://itunes.apple.com/search"
_TIMEOUT = 12.0


def search_apps(query: str, *, country: str = "US", limit: int = 8) -> list[dict]:
    """Return candidate apps for a name/genre term. `app_id` is the iOS App Store trackId,
    which is the Sensor Tower iOS app_id. Raises httpx.HTTPError on network/non-200."""
    params = {"term": query, "entity": "software", "country": country, "limit": limit}
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(_URL, params=params)
        r.raise_for_status()
        data = r.json()
    apps = []
    for res in data.get("results", []):
        tid = res.get("trackId")
        if tid is None:
            continue
        apps.append({
            "app_id": tid,
            "name": res.get("trackName"),
            "publisher": res.get("sellerName"),
            "genre": res.get("primaryGenreName"),
            "platform": "ios",
            "url": res.get("trackViewUrl"),
        })
    return apps
