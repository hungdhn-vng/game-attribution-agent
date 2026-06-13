import json
import pytest
from gaa.core.crawl.fetcher import CachedFetcher
from gaa.core.sources.providers.roblox import RobloxBenchmarkProvider

DISCOVER_URL = "http://roblox-api/discover?genre=survival"
SERIES_URL_1 = "http://roblox-api/series/111"
SERIES_URL_2 = "http://roblox-api/series/222"

DISCOVER_BODY = json.dumps({"games": [{"id": 111}, {"id": 222}, {"id": 333}]})
SERIES_BODY = json.dumps({"points": [
    {"date": "2026-05-01", "ccu": 5000},
    {"date": "2026-05-02", "ccu": 4900},
]})


def make_fetch_fn(url_map: dict):
    """Return a fetch_fn that dispatches to canned bodies by URL."""
    def fetch_fn(url: str) -> str:
        for key, body in url_map.items():
            if key in url:
                return body
        raise ValueError(f"Unexpected URL in test: {url}")
    return fetch_fn


def test_class_attrs():
    provider = RobloxBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="http://x/{genre}",
        series_url_tmpl="http://x/{id}",
    )
    assert provider.tier == "roblox"
    assert provider.produces == "quant"


def test_discover_returns_ids(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"discover": DISCOVER_BODY}),
    )
    provider = RobloxBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://roblox-api/discover?genre={genre}",
        series_url_tmpl="http://roblox-api/series/{id}",
    )
    ids = provider.discover("survival")
    assert ids == ["111", "222", "333"]


def test_discover_respects_max_comparators(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"discover": DISCOVER_BODY}),
    )
    provider = RobloxBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://roblox-api/discover?genre={genre}",
        series_url_tmpl="http://roblox-api/series/{id}",
        max_comparators=2,
    )
    ids = provider.discover("survival")
    assert ids == ["111", "222"]


def test_series_for_parses_ccu(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"series/111": SERIES_BODY}),
    )
    provider = RobloxBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://roblox-api/discover?genre={genre}",
        series_url_tmpl="http://roblox-api/series/{id}",
    )
    series = provider.series_for("111")
    assert series == {"2026-05-01": 5000.0, "2026-05-02": 4900.0}


def test_discover_malformed_json_returns_empty(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=lambda url: "not-json!!",
    )
    provider = RobloxBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://roblox-api/discover?genre={genre}",
        series_url_tmpl="http://roblox-api/series/{id}",
    )
    assert provider.discover("survival") == []


def test_series_for_malformed_json_returns_empty(tmp_path):
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=lambda url: "{bad json",
    )
    provider = RobloxBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="http://roblox-api/discover?genre={genre}",
        series_url_tmpl="http://roblox-api/series/{id}",
    )
    assert provider.series_for("111") == {}
