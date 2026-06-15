import json
import os
from gaa.mcp import tools


class FakeCtx:
    class settings:
        cache_dir = "/tmp"  # overridden per-test via GAA_RUN_SIDECAR


def test_analyze_success_writes_sidecar(tmp_path, monkeypatch):
    side = tmp_path / "last_run.json"
    monkeypatch.setenv("GAA_RUN_SIDECAR", str(side))
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "success", "run_id": "run-xyz"})
    r = tools.run_tool(FakeCtx(), "analyze", {"query": "why?"}, is_admin=False)
    assert r["run_id"] == "run-xyz"
    rec = json.loads(side.read_text())
    assert rec["run_id"] == "run-xyz" and isinstance(rec["ts"], (int, float))


def test_non_analyze_does_not_write_sidecar(tmp_path, monkeypatch):
    side = tmp_path / "last_run.json"
    monkeypatch.setenv("GAA_RUN_SIDECAR", str(side))
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "success"})
    tools.run_tool(FakeCtx(), "status", {"run": "r1"}, is_admin=False)
    assert not side.exists()


def test_failed_analyze_does_not_write_sidecar(tmp_path, monkeypatch):
    side = tmp_path / "last_run.json"
    monkeypatch.setenv("GAA_RUN_SIDECAR", str(side))
    monkeypatch.setattr(tools.actions, "dispatch",
                        lambda ctx, action, args, *, is_admin: {"status": "error", "error": "boom"})
    tools.run_tool(FakeCtx(), "analyze", {"query": "x"}, is_admin=False)
    assert not side.exists()
