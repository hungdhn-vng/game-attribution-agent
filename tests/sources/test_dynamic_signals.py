# tests/sources/test_dynamic_signals.py
from gaa.core.sources.dynamic import DynamicSignals

_JSON = ('{"signals": [{"date": "2026-06-04", "kind": "influencer", "scope": "game", '
         '"entity": "T", "reach": "1M", "url": "https://x", "summary": "s", '
         '"sentiment": 0.3}]}')


class _Cfg:
    def __init__(self, mode):
        self._mode = mode
    def resolve(self, name):
        if name == "benchmark_mode":
            return (self._mode, "store")
        return ("", "default")


class _Settings:
    cache_dir = "/tmp/gaa-test-cache"
    perplexity_api_key = "k"


def test_uses_social_provider_when_crawl_mode():
    ds = DynamicSignals(config=_Cfg("crawl"), settings=_Settings(),
                        answer_fn=lambda p: {"content": _JSON, "citations": []})
    out = ds.events("Real Game", "rpg", "2026-06-01", "2026-06-08")
    assert out and out[0]["kind"] == "influencer"


def test_falls_back_to_fixture_when_not_crawl():
    ds = DynamicSignals(config=_Cfg("snapshot"), settings=_Settings(),
                        answer_fn=lambda p: {"content": _JSON, "citations": []})
    assert ds.events("g", "rpg", "2026-06-01", "2026-06-08") == []
