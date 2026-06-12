import pytest
import httpx
from gaa.config import Settings
from gaa.crawl.perplexity import perplexity_answer


class _FakeResponse:
    def __init__(self, citations):
        self._citations = citations

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [{"message": {"content": "hi"}}],
            "citations": self._citations,
        }


def test_perplexity_answer_returns_content_and_citations(monkeypatch):
    monkeypatch.setattr(httpx, "post",
                        lambda *args, **kwargs: _FakeResponse([{"url": "u"}]))
    settings = Settings()
    settings.perplexity_api_key = "test-key"

    result = perplexity_answer("q", settings)

    assert result == {"content": "hi", "citations": [{"url": "u"}]}


def test_perplexity_answer_normalizes_string_citations(monkeypatch):
    """The live Perplexity API returns citations as plain URL strings —
    they must be normalized into {"url": ...} dicts for downstream consumers."""
    monkeypatch.setattr(httpx, "post",
                        lambda *args, **kwargs: _FakeResponse(
                            ["https://a.example/1", "https://b.example/2"]))
    settings = Settings()
    settings.perplexity_api_key = "test-key"

    result = perplexity_answer("q", settings)

    assert result["citations"] == [
        {"url": "https://a.example/1"},
        {"url": "https://b.example/2"},
    ]
