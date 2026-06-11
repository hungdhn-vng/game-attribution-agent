"""Tests for BenchmarkRefresher — Task A6."""
import time
import pytest
from gaa.store.benchmark_store import BenchmarkStore
from gaa.crawl.refresher import BenchmarkRefresher


# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------

class FakeQuantProvider:
    """Minimal quant provider with controllable data and call tracking."""

    tier = "roblox"
    produces = "quant"

    def __init__(self, ids: list[str], series: dict[str, float] | None = None):
        self._ids = ids
        self._series = series if series is not None else {"2026-05-01": 100.0, "2026-05-02": 90.0}
        self.discover_calls = 0
        self.series_calls = 0

    def discover(self, genre: str) -> list[str]:
        self.discover_calls += 1
        return list(self._ids)

    def series_for(self, comparator: str) -> dict[str, float]:
        self.series_calls += 1
        return dict(self._series)


class FakeThinProvider:
    """Returns only 1 data point — too thin to be stored as quant."""

    tier = "roblox"
    produces = "quant"

    def discover(self, genre: str) -> list[str]:
        return ["id1"]

    def series_for(self, comparator: str) -> dict[str, float]:
        return {"2026-05-01": 50.0}


_FAKE_WEB_DEFAULT = {
    "direction": "up",
    "summary": "Genre is growing.",
    "citations": [],
}

_SENTINEL = object()


class FakeWebProvider:
    """Minimal qual provider.

    Pass ``result=None`` explicitly to simulate a failed/empty lookup.
    Omit the argument (or pass a dict) to get the default success payload.
    """

    tier = "web"
    produces = "qual"

    def __init__(self, result=_SENTINEL):
        if result is _SENTINEL:
            self._result = dict(_FAKE_WEB_DEFAULT)
        else:
            self._result = result  # may be None

    def qualitative(self, genre: str, platform: str, start: str, end: str) -> dict | None:
        return self._result


class BrokenProvider:
    """Provider whose discover always raises."""

    tier = "broken"
    produces = "quant"

    def discover(self, genre: str) -> list[str]:
        raise RuntimeError("network error")

    def series_for(self, comparator: str) -> dict[str, float]:  # pragma: no cover
        return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_aggregation(tmp_path):
    """Two comparators each returning 2 dates → summed raw stored, points==2."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    provider = FakeQuantProvider(ids=["g1", "g2"])
    refresher = BenchmarkRefresher(store, {"roblox": [provider]})

    result = refresher.refresh("roblox", "Action")

    assert result["status"] == "ok"
    assert result["tier"] == "roblox"
    assert result["points"] == 2
    assert result["partial"] is False

    stored = store.get_quant("roblox", "Action")
    assert stored is not None
    assert stored["raw"]["2026-05-01"] == 200.0
    assert stored["raw"]["2026-05-02"] == 180.0
    assert stored["comparators"] == ["g1", "g2"]


def test_comparator_cap(tmp_path):
    """discover returns 10 ids but comparator_cap=3 means only 3 are fetched."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    ids = [str(i) for i in range(10)]
    provider = FakeQuantProvider(ids=ids)
    refresher = BenchmarkRefresher(store, {"roblox": [provider]}, comparator_cap=3)

    result = refresher.refresh("roblox", "Action")

    assert result["status"] == "ok"
    assert provider.series_calls == 3
    assert result["points"] == 2  # still 2 dates (summed across 3 comparators)


def test_quant_too_thin_web_fallback(tmp_path):
    """<2 dates from quant providers → falls back to web qual provider."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    web = FakeWebProvider()
    refresher = BenchmarkRefresher(
        store,
        {"roblox": [FakeThinProvider()]},
        web_provider=web,
    )

    result = refresher.refresh("roblox", "Action", start="2026-05-01", end="2026-05-02")

    assert result["status"] == "ok"
    assert result["tier"] == "web"
    assert result["qual"] is True
    assert result["points"] == 0

    stored_qual = store.get_qual("roblox", "Action")
    assert stored_qual is not None
    assert stored_qual["direction"] == "up"


def test_fresh_short_circuit(tmp_path):
    """After a successful refresh, a second call with default ttl returns status=='fresh'."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    provider = FakeQuantProvider(ids=["g1", "g2"])
    refresher = BenchmarkRefresher(store, {"roblox": [provider]}, ttl_s=21600)

    # First call populates the store
    r1 = refresher.refresh("roblox", "Action")
    assert r1["status"] == "ok"
    discover_after_first = provider.discover_calls

    # Second call should short-circuit
    r2 = refresher.refresh("roblox", "Action")
    assert r2["status"] == "fresh"
    assert r2["tier"] == "cache"
    assert r2["points"] == 0
    assert r2["partial"] is False

    # Provider was NOT called again
    assert provider.discover_calls == discover_after_first


def test_deadline_expired(tmp_path):
    """Passing an already-expired deadline causes partial=True with no real fetches."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    provider = FakeQuantProvider(ids=["g1", "g2"])
    refresher = BenchmarkRefresher(store, {"roblox": [provider]})

    # Deadline already passed
    expired = time.monotonic() - 1.0
    result = refresher.refresh("roblox", "Action", deadline=expired)

    assert result["partial"] is True
    # No full series should have been aggregated (deadline fires before first fetch)
    # The aggregate will be empty → status is empty or partial with 0 points
    assert result["points"] == 0


def test_broken_provider_skipped(tmp_path):
    """A provider whose discover raises is skipped without crashing the whole refresh."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    good_provider = FakeQuantProvider(ids=["g1", "g2"])
    refresher = BenchmarkRefresher(
        store,
        {"roblox": [BrokenProvider(), good_provider]},
    )

    result = refresher.refresh("roblox", "Action")

    # Good provider still ran and produced data
    assert result["status"] == "ok"
    assert result["points"] == 2


def test_no_providers_no_web(tmp_path):
    """No providers and no web_provider → status=='empty'."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    refresher = BenchmarkRefresher(store, {})

    result = refresher.refresh("roblox", "Action")

    assert result["status"] == "empty"
    assert result["tier"] is None
    assert result["points"] == 0


def test_web_provider_returns_none(tmp_path):
    """Web provider returning None → status=='empty'."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    web = FakeWebProvider(result=None)
    refresher = BenchmarkRefresher(
        store,
        {"roblox": [FakeThinProvider()]},
        web_provider=web,
    )

    result = refresher.refresh("roblox", "Action")

    assert result["status"] == "empty"
    assert result["tier"] is None


def test_unknown_platform_falls_back_to_web(tmp_path):
    """Platform with no registered providers triggers web fallback immediately."""
    store = BenchmarkStore(str(tmp_path / "bench.db"))
    web = FakeWebProvider()
    refresher = BenchmarkRefresher(store, {}, web_provider=web)

    result = refresher.refresh("unknown_platform", "Action")

    assert result["status"] == "ok"
    assert result["tier"] == "web"
    assert result["qual"] is True
