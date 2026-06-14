# tests/crawl/test_refresher_benchmark.py
from gaa.core.crawl.refresher import BenchmarkRefresher
from gaa.core.store.benchmark_store import BenchmarkStore


class _Web:
    def metric_benchmark(self, metric, genre, platform, start, end):
        return {"metric": metric, "low": 0.12, "high": 0.19, "source": "X",
                "confidence": "med", "citations": []}
    def qualitative(self, genre, platform, start, end):
        return None


def test_refresh_with_metric_stores_benchmark(tmp_path):
    store = BenchmarkStore(str(tmp_path / "b.sqlite"))
    ref = BenchmarkRefresher(store=store, providers_by_platform={}, web_provider=_Web())
    ref.refresh("roblox", "rpg", "2026-06-01", "2026-06-08", metric="retention_d1")
    b = store.get_benchmark("roblox", "rpg", "retention_d1")
    assert b is not None and b["high"] == 0.19


def test_refresh_without_metric_stores_no_benchmark(tmp_path):
    store = BenchmarkStore(str(tmp_path / "b.sqlite"))
    ref = BenchmarkRefresher(store=store, providers_by_platform={}, web_provider=_Web())
    ref.refresh("roblox", "rpg", "2026-06-01", "2026-06-08")
    assert store.get_benchmark("roblox", "rpg", "retention_d1") is None
