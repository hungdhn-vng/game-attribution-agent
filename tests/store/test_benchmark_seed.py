"""Tests for gaa.store.benchmark_seed.seed_benchmark_store."""
import json
import pytest
from gaa.store.benchmark_store import BenchmarkStore
from gaa.store.benchmark_seed import seed_benchmark_store


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(str(tmp_path / "bench.db"))


@pytest.fixture
def snapshot_file(tmp_path):
    """Write a small snapshot JSON and return its path."""
    data = {
        "roblox/survival": {
            "raw": {
                "2026-04-25": 5200,
                "2026-04-27": 5190,
                "2026-05-01": 5180,
            },
            "tier": "snapshot",
        }
    }
    p = tmp_path / "snapshot.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_seed_seeds_entry(store, snapshot_file):
    """A fresh store should have the entry seeded and get_quant returns it."""
    count = seed_benchmark_store(store, snapshot_file)
    assert count == 1
    result = store.get_quant("roblox", "survival")
    assert result is not None
    assert result["raw"] == {"2026-04-25": 5200, "2026-04-27": 5190, "2026-05-01": 5180}
    assert result["tier"] == "snapshot"


def test_seed_idempotent(store, snapshot_file):
    """Calling seed_benchmark_store twice must not overwrite existing data."""
    seed_benchmark_store(store, snapshot_file)
    # Overwrite the entry with different data via the store directly
    store.put_quant("roblox", "survival", raw={"2026-04-25": 9999.0}, meta={"tier": "live"})
    # Second seed call should skip the already-present entry
    count = seed_benchmark_store(store, snapshot_file)
    assert count == 0
    # The live value must still be there
    result = store.get_quant("roblox", "survival")
    assert result is not None
    assert result["raw"] == {"2026-04-25": 9999.0}
    assert result["tier"] == "live"


def test_seed_missing_path_returns_zero(store):
    """A non-existent snapshot path must return 0 without raising."""
    count = seed_benchmark_store(store, "/tmp/does_not_exist_abc123.json")
    assert count == 0


def test_seed_multiple_entries(store, tmp_path):
    """Multiple entries in the snapshot are all seeded."""
    data = {
        "roblox/survival": {
            "raw": {"2026-04-25": 5200, "2026-04-27": 5190, "2026-05-01": 5180},
            "tier": "snapshot",
        },
        "roblox/simulator": {
            "raw": {"2026-04-25": 8100, "2026-04-27": 8085, "2026-05-01": 8060},
            "tier": "snapshot",
        },
    }
    p = tmp_path / "multi.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    count = seed_benchmark_store(store, str(p))
    assert count == 2
    assert store.get_quant("roblox", "survival") is not None
    assert store.get_quant("roblox", "simulator") is not None
