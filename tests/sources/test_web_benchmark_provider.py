from gaa.core.sources.providers.web import WebSearchBenchmarkProvider


def _provider(payload_json, citations=None):
    return WebSearchBenchmarkProvider(
        lambda p: {"content": payload_json, "citations": citations or [{"url": "https://src"}]})


def test_percent_units_normalized_to_fraction_for_rate_metric():
    p = _provider('{"low": 12, "high": 19, "median": 15, "unit": "percent", '
                  '"source": "GA 2025", "confidence": "med"}')
    b = p.metric_benchmark("retention_d1", "rpg", "roblox", "2026-06-01", "2026-06-08")
    assert b["low"] == 0.12 and b["high"] == 0.19 and b["median"] == 0.15
    assert b["unit"] == "fraction" and b["source"] == "GA 2025"
    assert b["citations"] == [{"url": "https://src"}]


def test_unparseable_returns_none():
    assert _provider("not json").metric_benchmark(
        "retention_d1", "rpg", "roblox", "a", "b") is None


def test_missing_low_high_returns_none():
    assert _provider('{"source": "x"}').metric_benchmark(
        "retention_d1", "rpg", "roblox", "a", "b") is None
