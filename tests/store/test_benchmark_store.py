"""Tests for gaa.store.benchmark_store.BenchmarkStore."""
import time
import pytest
from gaa.store.benchmark_store import BenchmarkStore


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(str(tmp_path / "bench.db"))


# ── quant round-trip ──────────────────────────────────────────────────────────

def test_put_quant_get_quant_roundtrip(store):
    raw = {"2024-01-01": 100.0, "2024-01-02": 110.0}
    meta = {"source": "test", "window": "30d"}
    store.put_quant("steam", "action", raw, meta)
    result = store.get_quant("steam", "action")
    assert result is not None
    assert result["raw"] == raw
    assert result["source"] == "test"
    assert result["window"] == "30d"
    assert "fetched_at" in result


def test_put_quant_without_meta(store):
    raw = {"2024-01-01": 50.0, "2024-01-02": 60.0}
    store.put_quant("mobile", "puzzle", raw)
    result = store.get_quant("mobile", "puzzle")
    assert result is not None
    assert result["raw"] == raw
    assert "fetched_at" in result


def test_get_quant_missing_returns_none(store):
    result = store.get_quant("nonexistent", "genre")
    assert result is None


def test_put_quant_upserts(store):
    raw1 = {"2024-01-01": 100.0}
    raw2 = {"2024-01-01": 200.0}
    store.put_quant("steam", "rpg", raw1)
    store.put_quant("steam", "rpg", raw2)
    result = store.get_quant("steam", "rpg")
    assert result["raw"] == raw2


# ── qual round-trip ───────────────────────────────────────────────────────────

def test_put_qual_get_qual_roundtrip(store):
    payload = {"trend": "growing", "notes": "strong retention"}
    store.put_qual("steam", "strategy", payload)
    result = store.get_qual("steam", "strategy")
    assert result is not None
    assert result["trend"] == "growing"
    assert result["notes"] == "strong retention"
    assert "fetched_at" in result


def test_get_qual_missing_returns_none(store):
    result = store.get_qual("nonexistent", "genre")
    assert result is None


# ── is_fresh ──────────────────────────────────────────────────────────────────

def test_is_fresh_true_with_large_ttl(store):
    store.put_quant("steam", "action", {"2024-01-01": 100.0})
    assert store.is_fresh("steam", "action", "quant", ttl_s=86400.0) is True


def test_is_fresh_false_with_zero_ttl(store):
    store.put_quant("steam", "action", {"2024-01-01": 100.0})
    assert store.is_fresh("steam", "action", "quant", ttl_s=0.0) is False


def test_is_fresh_false_with_negative_ttl(store):
    store.put_quant("steam", "action", {"2024-01-01": 100.0})
    assert store.is_fresh("steam", "action", "quant", ttl_s=-1.0) is False


def test_is_fresh_false_when_missing(store):
    assert store.is_fresh("nonexistent", "genre", "quant", ttl_s=86400.0) is False


def test_is_fresh_works_for_qual_kind(store):
    store.put_qual("mobile", "casual", {"trend": "flat"})
    assert store.is_fresh("mobile", "casual", "qual", ttl_s=86400.0) is True
    assert store.is_fresh("mobile", "casual", "qual", ttl_s=0.0) is False
