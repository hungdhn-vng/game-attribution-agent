import json
from gaa.crawl.fetcher import CachedFetcher


class RobloxBenchmarkProvider:
    """Benchmark provider backed by public Roblox game tracker data.

    Inject ``fetch_fn`` via a ``CachedFetcher`` for deterministic offline tests.
    Real tracker endpoints are configured via URL templates confirmed at integration.
    """

    tier: str = "roblox"
    produces: str = "quant"

    def __init__(
        self,
        fetcher: CachedFetcher,
        discover_url_tmpl: str,
        series_url_tmpl: str,
        max_comparators: int = 5,
    ) -> None:
        self._fetcher = fetcher
        self._discover_tmpl = discover_url_tmpl
        self._series_tmpl = series_url_tmpl
        self._max = max_comparators

    def discover(self, genre: str) -> list[str]:
        """Fetch game list for *genre* and return up to max_comparators ids (as strings)."""
        url = self._discover_tmpl.format(genre=genre)
        try:
            body = self._fetcher.get(url)
            data = json.loads(body)
            games = data.get("games", [])
            return [str(g["id"]) for g in games[: self._max]]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def series_for(self, comparator: str) -> dict[str, float]:
        """Fetch CCU time-series for *comparator* id and return {date: ccu}."""
        url = self._series_tmpl.format(id=comparator)
        try:
            body = self._fetcher.get(url)
            data = json.loads(body)
            return {p["date"]: float(p["ccu"]) for p in data.get("points", [])}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return {}
