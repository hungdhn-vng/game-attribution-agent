import time
import time as _t
from gaa.mcp import tools
from gaa.mcp import tools as mcp_tools
from gaa.server import actions

class FakeCtx: pass


def _ctx_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "g.sqlite"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "g.toml"))
    from gaa.cli.wiring import build_context
    from gaa.core.llm.client import FakeLLM
    return build_context(llm=FakeLLM({}))


def _ctx(tmp_path, monkeypatch):
    return _ctx_env(tmp_path, monkeypatch)

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
# Sensor Tower browser-relay tools (st_*)
# ---------------------------------------------------------------------------

def test_st_tool_cache_hit_skips_relay(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    monkeypatch.setattr(mcp_tools, "_st_relay",
                        lambda built: (_ for _ in ()).throw(AssertionError("relay called on cache hit")))
    from gaa.sensortower import guard, cache
    args = {"app_ids": [111], "start_date": "2024-01-01", "end_date": "2024-02-01"}
    built = guard.build("st_app_performance", args, resolver=lambda l: None, today="2024-06-01")["built"]
    cache.put(cache.make_key(built), {"hit": True}, end_date="2024-02-01", now=_t.time())
    out = mcp_tools.run_tool(ctx, "st_app_performance", args, is_admin=False)
    assert out["cached"] is True and out["data"] == {"hit": True}

def test_st_tool_relay_on_miss(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    monkeypatch.setattr(mcp_tools, "_st_relay", lambda built: {"result": {"fresh": 1}})
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"app_ids": [222], "start_date": "2024-01-01", "end_date": "2024-02-01"}, is_admin=False)
    assert out["cached"] is False and out["data"] == {"fresh": 1}

def test_st_tool_not_connected(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    monkeypatch.setattr(mcp_tools, "_st_relay", lambda built: {"error": {"kind": "not_connected"}})
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"app_ids": [1], "start_date": "2024-01-01", "end_date": "2024-02-01"}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "not_connected"

def test_st_tool_need_app_id(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_tools, "_st_today", lambda: "2024-06-01")
    out = mcp_tools.run_tool(ctx, "st_app_performance",
                             {"labels": ["ghost"], "start_date": "2024-01-01", "end_date": "2024-02-01"}, is_admin=False)
    assert out["status"] == "error" and out["error"] == "need_app_id" and out["labels"] == ["ghost"]

def test_st_set_app_id_persists(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    # Create and save a minimal active profile so the tool has something to work with
    from gaa.core.schema.profile import GameProfile, ColumnMapping
    prof = GameProfile(
        name="test_game",
        platform="ios",
        genre="action",
        mapping=ColumnMapping(date_col="date", metric_cols={"installs": "installs"}),
    )
    ctx.profiles.save(prof)
    ctx.profiles.set_active(prof.name)
    out = mcp_tools.run_tool(ctx, "st_set_app_id", {"label": "self", "id": 999}, is_admin=False)
    assert out["status"] == "success"
    from gaa.sensortower import appids
    assert appids.resolve(ctx.settings.db_path, prof.name, "self")["id"] == 999
