import json

from gaa.notion import server


def test_build_server_lists_four_tools_and_calls(monkeypatch):
    monkeypatch.setattr(server.tools, "run_tool",
                        lambda name, args: {"status": "success", "echo": {"name": name, "args": args}})
    srv, listed, called = server._for_test_handles()
    names = {t.name for t in listed()}
    assert names == {"build_updates", "user_sentiment", "notion_search", "notion_fetch"}
    out = called("notion_search", {"query": "x"})
    assert json.loads(out[0].text) == {"status": "success",
                                       "echo": {"name": "notion_search", "args": {"query": "x"}}}
