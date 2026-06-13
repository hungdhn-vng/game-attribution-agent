import json
from typing import Callable, Optional
from gaa.core.crawl.fetcher import CachedFetcher


class RoMonitorBenchmark:
    """BenchmarkSource backed by public Roblox ecosystem CCU data.

    Confirm the real RoMonitor/Rolimon's endpoint + JSON shape at build time and adjust
    `_parse`; the injected `fetch_fn` keeps tests deterministic.
    """
    def __init__(self, cache_dir: str, genre_url_tmpl: str,
                 fetch_fn: Optional[Callable[[str], str]] = None) -> None:
        self._fetcher = CachedFetcher(cache_dir, fetch_fn)
        self._tmpl = genre_url_tmpl

    def _parse(self, body: str) -> dict:
        data = json.loads(body)
        return {p["date"]: float(p["ccu"]) for p in data.get("points", [])}

    def genre_trend(self, genre: str, start: str, end: str) -> dict:
        body = self._fetcher.get(self._tmpl.format(genre=genre))
        raw = {d: v for d, v in self._parse(body).items() if start <= d <= end}
        if len(raw) < 2:
            return {}
        base = raw[min(raw)]
        return {d: (v / base) * 100.0 for d, v in raw.items()} if base else {}
