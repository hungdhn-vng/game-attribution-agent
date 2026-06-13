from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import capabilities, actions, persona


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_exec_runs_command(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    r = capabilities.exec_action(ctx, type("A", (), {"command": "echo hello-gaa"})())
    assert r["status"] == "success"
    assert "hello-gaa" in r["stdout"]


def test_exec_missing_command(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    r = capabilities.exec_action(ctx, type("A", (), {"command": None})())
    assert r["status"] == "error"


def test_browse_extracts_text(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)

    class FakeResp:
        status_code = 200
        text = "<html><head><title>T</title></head><body><p>Hello world</p></body></html>"
        def raise_for_status(self): pass

    monkeypatch.setattr(capabilities.httpx, "get", lambda *a, **k: FakeResp())
    r = capabilities.browse_action(ctx, type("A", (), {"url": "http://x"})())
    assert r["status"] == "success"
    assert "Hello world" in r["text"]
    assert r["title"] == "T"


def test_self_edit_writes_and_is_registered_admin_mutating(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    r = capabilities.self_edit_action(
        ctx, type("A", (), {"target": "MEMORY.md", "content": "Learned: X.", "mode": "append"})())
    assert r["status"] == "success"
    assert "Learned: X." in persona.load_memory(ctx)
    # registered into the shared dispatch as admin + mutating
    assert "exec" in actions.ADMIN_ACTIONS
    assert "self_edit" in actions.MUTATING_ACTIONS


def test_dispatch_routes_exec_when_admin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    r = actions.dispatch(ctx, "exec", {"command": "echo via-dispatch"}, is_admin=True)
    assert r["status"] == "success" and "via-dispatch" in r["stdout"]
    r2 = actions.dispatch(ctx, "exec", {"command": "echo nope"}, is_admin=False)
    assert r2["status"] == "error" and "admin" in r2["error"].lower()
