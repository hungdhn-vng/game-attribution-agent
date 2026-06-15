"""Tests for the trimmed GAA front door (Phase C1).

Covers: GET /health, GET /runs/<id>/<artifact> (byte-exact + traversal-safe).
The old ChatAgent / /invocations tests are intentionally not included —
those routes were retired in C1 (OpenClaw is the loop now).
"""
import io
from fastapi.testclient import TestClient
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server.app import create_app

_SYNTH = {"main_story": "DAU fell.", "rationale": "x",
          "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
          "assumptions_and_gaps": []}


def _client(tmp_path, monkeypatch, *, token="t0k"):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    monkeypatch.setenv("GAA_AGENT_TOKEN", token)
    ctx = build_context(llm=FakeLLM(_SYNTH), today="2026-06-13")
    return TestClient(create_app(ctx=ctx)), ctx


def test_health_open(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200


def test_artifact_route_serves_byte_exact(tmp_path, monkeypatch):
    client, ctx = _client(tmp_path, monkeypatch)
    run = ctx.runs.create(session="s", query="why", suffix="aaaa")
    content = "<html>dossier</html>"
    (ctx.runs.path_for(run.run_id) / "report.html").write_text(content)
    ok = client.get(f"/runs/{run.run_id}/report.html")
    assert ok.status_code == 200 and ok.text == content


def test_artifact_unknown_name_is_404(tmp_path, monkeypatch):
    client, ctx = _client(tmp_path, monkeypatch)
    run = ctx.runs.create(session="s", query="why", suffix="aaaa")
    assert client.get(f"/runs/{run.run_id}/secret.txt").status_code == 404


def test_traversal_path_is_404(tmp_path, monkeypatch):
    """A run_id that escapes the runs root must be rejected."""
    client, ctx = _client(tmp_path, monkeypatch)
    runs_root = ctx.runs.path_for("__probe__").parent
    (runs_root.parent / "report.html").write_text("SECRET ABOVE ROOT")
    esc = client.get("/runs/%2e%2e/report.html")
    assert esc.status_code == 404
    assert "SECRET ABOVE ROOT" not in esc.text
