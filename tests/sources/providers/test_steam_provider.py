"""Tests for SteamBenchmarkProvider — real SteamCharts chart-data.json shape."""
import json
import pytest
from gaa.core.crawl.fetcher import CachedFetcher
from gaa.core.sources.providers.steam import SteamBenchmarkProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fetch_fn(url_map: dict):
    """Return a fetch_fn that dispatches to canned bodies by URL substring."""
    def fetch_fn(url: str) -> str:
        for key, body in url_map.items():
            if key in url:
                return body
        raise ValueError(f"Unexpected URL in test: {url}")
    return fetch_fn


def make_provider(tmp_path, fetch_fn=None, max_comparators=5, series_url_tmpl=""):
    """Build a SteamBenchmarkProvider wired to an in-memory fetcher."""
    fetcher = CachedFetcher(str(tmp_path), fetch_fn=fetch_fn) if fetch_fn else None
    return SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="",   # unused — curated map is built-in
        series_url_tmpl=series_url_tmpl,
        max_comparators=max_comparators,
    )


# ---------------------------------------------------------------------------
# Class-level attributes
# ---------------------------------------------------------------------------

def test_class_attrs():
    provider = SteamBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="",
        series_url_tmpl="",
    )
    assert provider.tier == "steam"
    assert provider.produces == "quant"


# ---------------------------------------------------------------------------
# series_for — real SteamCharts [ts_ms, players] list shape
# ---------------------------------------------------------------------------

# The two canonical test timestamps and their expected ISO dates:
#   1385856000000 -> 2013-12-01
#   1388534400000 -> 2014-01-01
REAL_SERIES_BODY = "[[1385856000000, 22571],[1388534400000, 51872]]"


def test_series_for_parses_real_shape(tmp_path):
    """series_for must parse [[ts_ms, players], ...] list and return {iso_date: float}."""
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"chart-data.json": REAL_SERIES_BODY}),
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="",
        series_url_tmpl="https://steamcharts.com/app/{id}/chart-data.json",
    )
    series = provider.series_for("252490")
    assert series == {"2013-12-01": 22571.0, "2014-01-01": 51872.0}


def test_series_for_malformed_string_returns_empty(tmp_path):
    """Non-JSON payload must yield {}."""
    fetcher = CachedFetcher(str(tmp_path), fetch_fn=lambda url: "not json")
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="",
        series_url_tmpl="https://steamcharts.com/app/{id}/chart-data.json",
    )
    assert provider.series_for("252490") == {}


def test_series_for_dict_payload_returns_empty(tmp_path):
    """A JSON object (wrong shape) must yield {}."""
    fetcher = CachedFetcher(str(tmp_path), fetch_fn=lambda url: "{}")
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="",
        series_url_tmpl="https://steamcharts.com/app/{id}/chart-data.json",
    )
    assert provider.series_for("252490") == {}


def _make_pairs(n: int) -> str:
    """Return a JSON list of n [ts_ms, players] pairs (1 day apart from epoch)."""
    base_ms = 1_000_000_000_000  # arbitrary base
    day_ms = 86_400_000
    pairs = [[base_ms + i * day_ms, float(i)] for i in range(n)]
    return json.dumps(pairs)


def test_series_for_respects_last_60_cap(tmp_path):
    """Feed 70 points; only the last 60 (most recent) should be returned."""
    body_70 = _make_pairs(70)
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"chart-data.json": body_70}),
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="",
        series_url_tmpl="https://steamcharts.com/app/{id}/chart-data.json",
    )
    series = provider.series_for("1")
    assert len(series) == 60
    # The last 60 rows have player values 10..69
    assert set(series.values()) == set(float(i) for i in range(10, 70))


def test_series_for_default_url_used_when_tmpl_empty(tmp_path):
    """When series_url_tmpl is empty the default SteamCharts URL is used."""
    fetcher = CachedFetcher(
        str(tmp_path),
        fetch_fn=make_fetch_fn({"chart-data.json": REAL_SERIES_BODY}),
    )
    provider = SteamBenchmarkProvider(
        fetcher=fetcher,
        discover_url_tmpl="",
        series_url_tmpl="",          # empty → should fall back to default
    )
    series = provider.series_for("252490")
    assert series == {"2013-12-01": 22571.0, "2014-01-01": 51872.0}


# ---------------------------------------------------------------------------
# discover — curated genre→appids map (no HTTP)
# ---------------------------------------------------------------------------

def test_discover_survival_returns_appids():
    """discover('survival') must return a non-empty list of known appid strings."""
    provider = SteamBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="",
        series_url_tmpl="",
    )
    ids = provider.discover("survival")
    assert len(ids) > 0
    # All entries must be numeric strings (valid Steam appids)
    assert all(s.isdigit() for s in ids)
    # Known canonical Rust appid must be present
    assert "252490" in ids


def test_discover_respects_max_comparators():
    """discover must not return more than max_comparators entries."""
    provider = SteamBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="",
        series_url_tmpl="",
        max_comparators=2,
    )
    ids = provider.discover("survival")
    assert len(ids) <= 2


def test_discover_unknown_genre_returns_empty():
    """An unlisted genre must return []."""
    provider = SteamBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="",
        series_url_tmpl="",
    )
    assert provider.discover("zxqnotagenre") == []


def test_discover_is_case_insensitive():
    """Genre lookup must be case-insensitive."""
    provider = SteamBenchmarkProvider(
        fetcher=None,
        discover_url_tmpl="",
        series_url_tmpl="",
    )
    assert provider.discover("Survival") == provider.discover("survival")
    assert provider.discover("ACTION") == provider.discover("action")
