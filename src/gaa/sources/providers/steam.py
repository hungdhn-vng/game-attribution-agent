import json
from gaa.crawl.fetcher import CachedFetcher


class SteamBenchmarkProvider:
    """Benchmark provider backed by public Steam concurrent-player data.

    Inject ``fetch_fn`` via a ``CachedFetcher`` for deterministic offline tests.
    Real tracker endpoints are configured via URL templates confirmed at integration.
    """

    tier: str = "steam"
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
        """Fetch app list for *genre* and return up to max_comparators appids (as strings)."""
        url = self._discover_tmpl.format(genre=genre)
        try:
            body = self._fetcher.get(url)
            data = json.loads(body)
            apps = data.get("apps", [])
            return [str(a["appid"]) for a in apps[: self._max]]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def series_for(self, comparator: str) -> dict[str, float]:
        """Fetch player-count time-series for *comparator* appid and return {date: players}."""
        url = self._series_tmpl.format(id=comparator)
        try:
            body = self._fetcher.get(url)
            data = json.loads(body)
            return {p["date"]: float(p["players"]) for p in data.get("points", [])}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return {}
