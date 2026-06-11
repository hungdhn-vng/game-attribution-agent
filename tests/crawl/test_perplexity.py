import pytest
import httpx
from gaa.config import Settings
from gaa.crawl.perplexity import perplexity_answer


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [{"message": {"content": "hi"}}],
            "citations": [{"url": "u"}],
        }


def test_perplexity_answer_returns_content_and_citations(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _FakeResponse())
    settings = Settings()
    settings.perplexity_api_key = "test-key"

    result = perplexity_answer("q", settings)

    assert result == {"content": "hi", "citations": [{"url": "u"}]}
