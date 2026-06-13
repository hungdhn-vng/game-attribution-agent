import pytest
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource


# ── fixtures ──────────────────────────────────────────────────────────────────

RAW = {"2026-05-01": 1000, "2026-05-02": 990, "2026-05-03": 980}


@pytest.fixture()
def store(tmp_path):
    s = BenchmarkStore(str(tmp_path / "bench.db"))
    s.put_quant("roblox", "survival", raw=RAW, meta={"tier": "roblox"})
    return s


@pytest.fixture()
def src(store):
    source = CrawlingBenchmarkSource(store)
    source.set_platform("roblox")
    return source


# ── genre_trend tests ─────────────────────────────────────────────────────────

def test_genre_trend_first_point_is_100(src):
    t = src.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert t["2026-05-01"] == 100.0


def test_genre_trend_last_point_approx_98(src):
    t = src.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert round(t["2026-05-03"], 1) == 98.0


def test_genre_trend_window_filtering(src):
    """A narrower window should only return in-window indexed points."""
    t = src.genre_trend("survival", "2026-05-02", "2026-05-03")
    # window start is 2026-05-02 → that becomes 100.0
    assert "2026-05-01" not in t
    assert t["2026-05-02"] == 100.0
    assert round(t["2026-05-03"], 4) == round((980 / 990) * 100.0, 4)


def test_genre_trend_miss_returns_empty(store):
    """Platform/genre not stored → {}."""
    source = CrawlingBenchmarkSource(store)
    source.set_platform("steam")
    assert source.genre_trend("survival", "2026-05-01", "2026-05-03") == {}


def test_genre_trend_missing_genre_returns_empty(src):
    assert src.genre_trend("unknown-genre", "2026-05-01", "2026-05-03") == {}


# ── qualitative_context tests ─────────────────────────────────────────────────

def test_qualitative_context_returns_stored_dict(store):
    qual = {"direction": "down", "summary": "declining", "citations": []}
    store.put_qual("roblox", "survival", qual)
    source = CrawlingBenchmarkSource(store)
    source.set_platform("roblox")
    result = source.qualitative_context("survival")
    assert result is not None
    assert result["direction"] == "down"
    assert result["summary"] == "declining"
    assert result["citations"] == []


def test_qualitative_context_missing_returns_none(src):
    assert src.qualitative_context("no-such-genre") is None
