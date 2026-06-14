from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.store.benchmark_store import BenchmarkStore


def test_metric_benchmark_reads_store(tmp_path):
    store = BenchmarkStore(str(tmp_path / "b.sqlite"))
    store.put_benchmark("roblox", "rpg", "retention_d1", {"low": 0.12, "high": 0.19})
    src = CrawlingBenchmarkSource(store)
    src.set_platform("roblox")
    assert src.metric_benchmark("retention_d1", "rpg")["low"] == 0.12
    assert src.metric_benchmark("dau", "rpg") is None
