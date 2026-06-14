# tests/runs/test_pipeline_crawl_metric.py
from gaa.core.sources.dynamic import DynamicRefresher


class _Cfg:
    def resolve(self, name):
        return ("snapshot", "default") if name == "benchmark_mode" else ("", "default")


class _Settings:
    cache_dir = "/tmp/gaa-test-cache"
    perplexity_api_key = ""


class _FakeStore:
    def is_fresh(self, *a, **k):
        return False
    def put_quant(self, *a, **k):
        pass
    def put_qual(self, *a, **k):
        pass
    def put_benchmark(self, *a, **k):
        pass


def test_dynamic_refresher_accepts_metric_kwarg():
    # snapshot mode → empty providers, no web; must accept metric without error
    r = DynamicRefresher(config=_Cfg(), settings=_Settings(), store=_FakeStore())
    out = r.refresh("roblox", "rpg", "2026-06-01", "2026-06-08", metric="retention_d1")
    assert isinstance(out, dict)
