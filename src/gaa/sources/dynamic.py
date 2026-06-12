"""Config-driven source facades.

These rebuild their underlying provider stack from the current ConfigStore values
on every call, so admin config changes take effect on the next job without a
process restart — and AnalysisPipeline keeps its existing refresher/signals API.
"""
import dataclasses
import os

from gaa.config import Settings
from gaa.crawl.fetcher import CachedFetcher
from gaa.crawl.perplexity import perplexity_answer
from gaa.crawl.refresher import BenchmarkRefresher
from gaa.sources.fixtures import FixtureSignalsSource
from gaa.sources.providers.roblox import RobloxBenchmarkProvider
from gaa.sources.providers.steam import SteamBenchmarkProvider
from gaa.sources.providers.web import WebSearchBenchmarkProvider
from gaa.sources.web_signals import WebSignalsSource
from gaa.store.config_store import ConfigStore


class DynamicRefresher:
    """BenchmarkRefresher facade that honors the live ConfigStore on each refresh."""

    def __init__(self, config: ConfigStore, settings: Settings, store) -> None:
        self._config = config
        self._settings = settings
        self._store = store

    def _cfg(self, name: str) -> str:
        return self._config.resolve(name)[0]

    def _build(self) -> BenchmarkRefresher:
        if self._cfg("benchmark_mode") != "crawl":
            return BenchmarkRefresher(store=self._store,
                                      providers_by_platform={}, web_provider=None)
        cache = self._settings.cache_dir + "/benchmark"
        providers = {
            "roblox": [RobloxBenchmarkProvider(
                fetcher=CachedFetcher(cache),
                discover_url_tmpl=self._cfg("roblox_discover_url_tmpl"),
                series_url_tmpl=self._cfg("roblox_series_url_tmpl"),
            )],
            "steam": [SteamBenchmarkProvider(
                fetcher=CachedFetcher(cache),
                # discover_url_tmpl is unused for Steam — SteamCharts has no genre
                # endpoint; kept for interface compatibility.
                discover_url_tmpl=os.environ.get("GAA_STEAM_DISCOVER_URL_TMPL", ""),
                series_url_tmpl=self._cfg("steam_series_url_tmpl"),
            )],
        }
        pkey = self._cfg("perplexity_api_key")
        web = None
        if pkey:
            psettings = dataclasses.replace(self._settings, perplexity_api_key=pkey)
            web = WebSearchBenchmarkProvider(
                lambda prompt: perplexity_answer(prompt, psettings))
        return BenchmarkRefresher(store=self._store,
                                  providers_by_platform=providers, web_provider=web)

    def refresh(self, platform, genre, start=None, end=None, deadline=None) -> dict:
        return self._build().refresh(platform, genre, start, end, deadline=deadline)


class DynamicSignals:
    """SignalsSource facade that honors the live ConfigStore on each call."""

    def __init__(self, config: ConfigStore, settings: Settings) -> None:
        self._config = config
        self._settings = settings

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        tmpl = self._config.resolve("signals_url_tmpl")[0]
        src = (WebSignalsSource(cache_dir=self._settings.cache_dir + "/signals",
                                query_url_tmpl=tmpl)
               if tmpl else FixtureSignalsSource([]))
        return src.events(game, genre, start, end)
