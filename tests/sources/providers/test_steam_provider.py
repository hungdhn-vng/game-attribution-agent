import json
import pytest
from gaa.crawl.fetcher import CachedFetcher
from gaa.sources.providers.steam import SteamBenchmarkProvider

DISCOVER_BODY = json.dumps({"apps": [{"appid": 730}, {"appid": 570}, {"appid": 440}]})
SERIES_BODY = json.dumps({"points": [
    {"date": "2026-05-01", "players": 800000},
    {"date": "2026-05-02", "players": 750000},
]})


def make_fetch_fn(url_map: dict):
    """Return a fetch_fn that dispatches to canned bodies by URL substring."""
    def fetch_fn(url: str) -> str:
        for key, body in url_map.items():
            if key in url:
                return body
        raise ValueError(f"Unexpected URL in test: {url}")
    return fetch_fn


def test_class_attrs():
    provider = SteamBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="http://x/{genre}",
        series_url_tmpl="http://x/{id}",
    )
    assert provider.tier == "steam"
    assert provider.produces == "quant"


def test_discover_returns_appids(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"discover": DISCOVER_BODY}),
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://steam-api/discover?genre={genre}",
        series_url_tmpl="http://steam-api/series/{id}",
    )
    ids = provider.discover("action")
    assert ids == ["730", "570", "440"]


def test_discover_respects_max_comparators(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"discover": DISCOVER_BODY}),
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://steam-api/discover?genre={genre}",
        series_url_tmpl="http://steam-api/series/{id}",
        max_comparators=2,
    )
    ids = provider.discover("action")
    assert ids == ["730", "570"]


def test_series_for_parses_players(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"series/730": SERIES_BODY}),
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://steam-api/discover?genre={genre}",
        series_url_tmpl="http://steam-api/series/{id}",
    )
    series = provider.series_for("730")
    assert series == {"2026-05-01": 800000.0, "2026-05-02": 750000.0}


def test_discover_malformed_json_returns_empty(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=lambda url: "not-json!!",
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://steam-api/discover?genre={genre}",
        series_url_tmpl="http://steam-api/series/{id}",
    )
    assert provider.discover("action") == []


def test_series_for_malformed_json_returns_empty(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=lambda url: "{bad json",
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://steam-api/discover?genre={genre}",
        series_url_tmpl="http://steam-api/series/{id}",
    )
    assert provider.series_for("730") == {}
