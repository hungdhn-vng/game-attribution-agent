from gaa.mcp import tools
from gaa.server import actions

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


# ---------------------------------------------------------------------------
# vStorage snapshot on mutating actions
# ---------------------------------------------------------------------------

def test_mutating_action_success_calls_snapshot(monkeypatch):
    """A MUTATING_ACTIONS tool that returns status=success must call persist.snapshot."""
    snapshot_calls = []
    # pick a mutating action that is also admin (so we pass is_admin=True)
    assert "config_set" in actions.MUTATING_ACTIONS
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "success"})
    monkeypatch.setattr(tools.persist, "snapshot", lambda ctx: snapshot_calls.append(ctx) or True)
    tools.run_tool(FakeCtx(), "config_set", {"key": "k", "value": "v"}, is_admin=True)
    assert len(snapshot_calls) == 1


def test_non_mutating_action_success_does_not_snapshot(monkeypatch):
    """A read-only action (e.g. status) must NOT trigger snapshot even on success."""
    snapshot_calls = []
    assert "status" not in actions.MUTATING_ACTIONS
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "success"})
    monkeypatch.setattr(tools.persist, "snapshot", lambda ctx: snapshot_calls.append(ctx) or True)
    tools.run_tool(FakeCtx(), "status", {"run": "r-1"}, is_admin=False)
    assert len(snapshot_calls) == 0


def test_analyze_success_does_not_snapshot(monkeypatch):
    """analyze returns status='done' (not 'success') and is not in MUTATING_ACTIONS,
    so it must never trigger a snapshot."""
    snapshot_calls = []
    assert "analyze" not in actions.MUTATING_ACTIONS
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "done", "run_id": "r-abc"})
    monkeypatch.setattr(tools.persist, "snapshot", lambda ctx: snapshot_calls.append(ctx) or True)
    tools.run_tool(FakeCtx(), "analyze", {"query": "why?"}, is_admin=False)
    assert len(snapshot_calls) == 0


def test_mutating_action_error_does_not_snapshot(monkeypatch):
    """A mutating action that returns status=error must NOT call snapshot."""
    snapshot_calls = []
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "error", "error": "oops"})
    monkeypatch.setattr(tools.persist, "snapshot", lambda ctx: snapshot_calls.append(ctx) or True)
    tools.run_tool(FakeCtx(), "config_set", {"key": "k", "value": "v"}, is_admin=True)
    assert len(snapshot_calls) == 0
