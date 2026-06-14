from gaa.core.crawl.research import research_json


def test_parses_object_and_attaches_citations():
    answer = lambda p: {"content": 'noise {"low": 12, "high": 19} tail',
                        "citations": [{"url": "https://x"}]}
    out = research_json(answer, "prompt")
    assert out["low"] == 12 and out["high"] == 19
    assert out["citations"] == [{"url": "https://x"}]


def test_returns_none_when_no_json():
    out = research_json(lambda p: {"content": "no json here", "citations": []}, "p")
    assert out is None


def test_returns_none_when_answer_fn_raises():
    def boom(p):
        raise RuntimeError("network down")
    assert research_json(boom, "p") is None
