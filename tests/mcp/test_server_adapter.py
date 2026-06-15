import json
from gaa.mcp import server

def test_build_server_lists_and_calls(monkeypatch):
    monkeypatch.setattr(server, "build_context", lambda: object())
    monkeypatch.setattr(server.tools, "run_tool",
                        lambda ctx, name, args, *, is_admin: {"status": "success", "echo": args})
    srv, listed, called = server._for_test_handles(is_admin=True)
    names = [t.name for t in listed()]
    assert "analyze" in names
    out = called("analyze", {"query": "x"})
    assert json.loads(out[0].text) == {"status": "success", "echo": {"query": "x"}}
