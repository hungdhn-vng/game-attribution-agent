import types
from gaa.server import actions


def _ns(**kw):
    ns = types.SimpleNamespace(**kw)
    ns.__class__ = type("A", (types.SimpleNamespace,), {"__getattr__": lambda s, n: None})
    return ns


def test_dispatch_gates_management_tools_non_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.cli.wiring import build_context
    ctx = build_context()
    r = actions.dispatch(ctx, "mcp_add", {"name": "c", "command": "npx"}, is_admin=False)
    assert r["status"] == "error" and "admin" in r["error"]


def test_mcp_add_and_list_as_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.cli.wiring import build_context
    ctx = build_context()
    r = actions.dispatch(ctx, "mcp_add",
                         {"name": "crawler", "command": "npx", "args": ["x"],
                          "env": {"K": "K"}}, is_admin=True)
    assert r["status"] == "success"
    lst = actions.dispatch(ctx, "mcp_list", {}, is_admin=True)
    assert "crawler" in [s["name"] for s in lst["servers"]]


def test_secret_set_list_hides_values(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.cli.wiring import build_context
    ctx = build_context()
    actions.dispatch(ctx, "secret_set", {"name": "K", "value": "v"}, is_admin=True)
    r = actions.dispatch(ctx, "secret_list", {}, is_admin=True)
    assert r["names"] == ["K"]
    assert "v" not in str(r)


def test_management_tools_are_admin_and_mutating():
    for a in ("mcp_add", "mcp_remove", "secret_set", "secret_unset"):
        assert a in actions.ADMIN_ACTIONS and a in actions.MUTATING_ACTIONS
    for a in ("mcp_list", "secret_list"):
        assert a in actions.ADMIN_ACTIONS and a not in actions.MUTATING_ACTIONS
