from gaa.core.sources.providers.web import WebSearchBenchmarkProvider


def _good_answer_fn(prompt: str) -> dict:
    return {
        "content": '{"direction":"down","summary":"genre cooling"}',
        "citations": [{"title": "X", "url": "http://x"}],
    }


def _malformed_answer_fn(prompt: str) -> dict:
    return {"content": "no json", "citations": []}


def test_qualitative_happy_path():
    provider = WebSearchBenchmarkProvider(answer_fn=_good_answer_fn)
    result = provider.qualitative(
        genre="survival", platform="roblox", start="2026-01-01", end="2026-06-01"
    )
    assert result == {
        "direction": "down",
        "summary": "genre cooling",
        "citations": [{"title": "X", "url": "http://x"}],
    }


def test_qualitative_malformed_returns_none():
    provider = WebSearchBenchmarkProvider(answer_fn=_malformed_answer_fn)
    result = provider.qualitative(
        genre="survival", platform="roblox", start="2026-01-01", end="2026-06-01"
    )
    assert result is None


def test_class_attrs():
    provider = WebSearchBenchmarkProvider(answer_fn=_good_answer_fn)
    assert provider.tier == "web"
    assert provider.produces == "qual"
