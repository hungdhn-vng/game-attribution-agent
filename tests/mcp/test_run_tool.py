from gaa.mcp import tools

class FakeCtx: pass

def test_unknown_tool_returns_error():
    r = tools.run_tool(FakeCtx(), "nope", {}, is_admin=True)
    assert r["status"] == "error" and "unknown" in r["error"].lower()

def test_missing_required_arg_rejected_before_dispatch():
    r = tools.run_tool(FakeCtx(), "analyze", {}, is_admin=False)
    assert r["status"] == "error" and "query" in r["error"]

def test_admin_tool_blocked_for_non_admin():
    r = tools.run_tool(FakeCtx(), "config_set", {"key": "k", "value": "v"}, is_admin=False)
    assert r["status"] == "error" and "admin" in r["error"].lower()

def test_valid_call_reaches_dispatch(monkeypatch):
    seen = {}
    def fake_dispatch(ctx, action, args, *, is_admin):
        seen.update(action=action, args=args, is_admin=is_admin)
        return {"status": "success", "run_id": "r-1"}
    monkeypatch.setattr(tools.actions, "dispatch", fake_dispatch)
    r = tools.run_tool(FakeCtx(), "analyze", {"query": "why drop?"}, is_admin=False)
    assert r == {"status": "success", "run_id": "r-1"}
    assert seen == {"action": "analyze", "args": {"query": "why drop?"}, "is_admin": False}
