import json
from datetime import datetime
from gaa.crawl.fetcher import CachedFetcher


_DEFAULT_SERIES_URL_TMPL = "https://steamcharts.com/app/{id}/chart-data.json"

# Curated genre → appid map. This is a best-effort starter set; SteamCharts
# has no genre-discovery endpoint, so genre discovery is handled entirely here.
# Add or adjust entries as new titles become relevant.
_GENRE_APPIDS: dict[str, list[str]] = {
    "survival": ["252490", "304930", "346110"],   # Rust, Unturned, ARK
    "action": ["730", "578080", "1172620"],        # CS2, PUBG, Sea of Thieves
    "simulator": ["255710", "8930", "1284210"],    # Cities Skylines, Civ5, It Takes Two
    "rpg": ["570", "374320", "1086940"],           # Dota 2, Dark Souls 3, Monster Hunter Rise
    "shooter": ["440", "359550", "1091500"],       # TF2, Rainbow Six Siege, Cyberpunk 2077
}


class SteamBenchmarkProvider:
    """Benchmark provider backed by public SteamCharts concurrent-player data.

    Inject ``fetch_fn`` via a ``CachedFetcher`` for deterministic offline tests.
    The series URL template defaults to the real SteamCharts chart-data.json
    endpoint; genre discovery is handled via the built-in ``_GENRE_APPIDS``
    curated map (SteamCharts has no genre-discovery API endpoint).
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
        # discover_url_tmpl is unused for Steam — SteamCharts has no genre
        # endpoint; discovery is served from the built-in _GENRE_APPIDS map.
        # Kept in the signature for interface compatibility with other providers.
        self._discover_tmpl = discover_url_tmpl
        self._series_url_tmpl = (
            series_url_tmpl if series_url_tmpl else _DEFAULT_SERIES_URL_TMPL
        )
        self._max_comparators = max_comparators

    def discover(self, genre: str) -> list[str]:
        """Return up to max_comparators appids for *genre* from the curated map.

        Uses the built-in ``_GENRE_APPIDS`` dict; no HTTP request is made.
        """
        return _GENRE_APPIDS.get(genre.lower(), [])[: self._max_comparators]

    def series_for(self, appid: str) -> dict[str, float]:
        """Fetch player-count time-series for *appid* and return {iso_date: players}.

        Parses the real SteamCharts chart-data.json shape: a JSON list of
        ``[unix_ms, players]`` pairs ordered oldest→newest. Returns the last 60
        points (most recent) to bound response size. Returns ``{}`` on any
        malformed or empty payload.
        """
        url = self._series_url_tmpl.format(id=appid)
        try:
            body = self._fetcher.get(url)
            data = json.loads(body)
            # Expect a list of [ts_ms, players] pairs; reject any other shape
            if not isinstance(data, list):
                return {}
            # Keep only the last 60 points (most recent)
            points = data[-60:]
            result: dict[str, float] = {}
            for entry in points:
                ts_ms, players = entry[0], entry[1]
                iso_date = datetime.utcfromtimestamp(ts_ms / 1000).date().isoformat()
                result[iso_date] = float(players)
            return result
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError):
            return {}
