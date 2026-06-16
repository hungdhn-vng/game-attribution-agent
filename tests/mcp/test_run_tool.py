import time
from gaa.mcp import tools
from gaa.mcp import tools as mcp_tools
from gaa.server import actions
from gaa.sensortower import store

class FakeCtx: pass


def _ctx_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "g.sqlite"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "g.toml"))
    from gaa.cli.wiring import build_context
    from gaa.core.llm.client import FakeLLM
    return build_context(llm=FakeLLM({}))

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


# ---------------------------------------------------------------------------
# Sensor Tower MCP tools
# ---------------------------------------------------------------------------

def test_st_status_reports_disconnected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    out = mcp_tools.run_tool(ctx, "sensor_tower_status", {}, is_admin=False)
    assert out["connected"] is False

def test_st_status_reports_connected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "a", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    out = mcp_tools.run_tool(ctx, "sensor_tower_status", {}, is_admin=False)
    assert out["connected"] is True and out["expires_in"] > 0

def test_st_connect_returns_authorize_url(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_build_authorize_url",
                        lambda session: "https://h.test/authorize?state=x")
    out = mcp_tools.run_tool(ctx, "sensor_tower_connect", {}, is_admin=False)
    assert out["authorize_url"].startswith("https://h.test/authorize")

def test_st_connect_failure_returns_connect_failed(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    def _boom(session):
        raise RuntimeError("discovery down")
    monkeypatch.setattr(mcp_tools, "_st_build_authorize_url", _boom)
    out = mcp_tools.run_tool(ctx, "sensor_tower_connect", {}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "connect_failed"

def test_st_call_upstream_error(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "AT", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    def _boom(token, name, args):
        raise RuntimeError("ST 500")
    monkeypatch.setattr(mcp_tools, "_st_call_tool", _boom)
    out = mcp_tools.run_tool(ctx, "sensor_tower_call", {"tool": "get_app"}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "upstream_error"

def test_st_list_tools_upstream_error(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "AT", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    def _boom(token):
        raise RuntimeError("ST 500")
    monkeypatch.setattr(mcp_tools, "_st_list_tools", _boom)
    out = mcp_tools.run_tool(ctx, "sensor_tower_list_tools", {}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "upstream_error"

def test_st_list_tools_not_connected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    out = mcp_tools.run_tool(ctx, "sensor_tower_list_tools", {}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "not_connected"

def test_st_call_forwards_when_connected(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "AT", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    monkeypatch.setattr(mcp_tools, "_st_call_tool",
                        lambda token, name, args: {"content": [f"{name}:{args}"]})
    out = mcp_tools.run_tool(ctx, "sensor_tower_call",
                             {"tool": "get_app", "arguments": {"id": "1"}}, is_admin=False)
    assert out["content"] == ["get_app:{'id': '1'}"]

def test_st_call_missing_tool_arg_is_bad_args(tmp_path, monkeypatch):
    ctx = _ctx_env(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "AT", "refresh_token": "r",
                                 "expiry": time.time() + 999})
    # 'tool' is required by the schema → schema validation should reject before routing
    out = mcp_tools.run_tool(ctx, "sensor_tower_call", {}, is_admin=False)
    assert out["status"] == "error"
