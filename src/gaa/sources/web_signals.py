import json
from typing import Callable, Optional
from urllib.parse import quote
from gaa.crawl.fetcher import CachedFetcher


class WebSignalsSource:
    """SignalsSource backed by public news/social/update feeds.

    Confirm the real news/Reddit/Roblox-updates endpoints at build time; `_parse` expects
    a JSON list of items and is the seam to adjust.
    """
    def __init__(self, cache_dir: str, query_url_tmpl: str,
                 fetch_fn: Optional[Callable[[str], str]] = None) -> None:
        self._fetcher = CachedFetcher(cache_dir, fetch_fn)
        self._tmpl = query_url_tmpl

    def _parse(self, body: str) -> list:
        return json.loads(body)

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        body = self._fetcher.get(self._tmpl.format(game=quote(game)))
        return [e for e in self._parse(body) if start <= e["date"] <= end]
