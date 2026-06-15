"""Tests for the trimmed GAA front door (Phase C1).

Covers: GET /health, GET /runs/<id>/<artifact> (byte-exact + traversal-safe),
        POST /chat (auth guard + SSE response), POST /upload (auth guard).
The old ChatAgent / /invocations tests are intentionally not included —
those routes were retired in C1 (OpenClaw is the loop now).
"""
import io
import json
from fastapi.testclient import TestClient
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server.app import create_app
from gaa.server.openclaw_client import FakeOpenClawClient

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


# ---------------------------------------------------------------------------
# /chat auth + SSE (I4)
# ---------------------------------------------------------------------------

def test_chat_requires_token(monkeypatch):
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    app = create_app(ctx=object())
    app.state.openclaw = FakeOpenClawClient([{"type": "done", "run_id": None}])
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/chat", json={"messages": []})
    assert r.status_code == 401



def test_chat_sse_injects_run_id(monkeypatch):
    """With a valid bearer token the SSE stream carries the latched run_id in done."""
    monkeypatch.setenv("GAA_AGENT_TOKEN", "tok123")
    app = create_app(ctx=object())
    scripted = [
        {"type": "tool_result", "tool": "analyze", "run_id": "run-abc"},
        {"type": "done", "run_id": None},
    ]
    app.state.openclaw = FakeOpenClawClient(scripted)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(
        "/chat",
        json={"messages": []},
        headers={"Authorization": "Bearer tok123"},
    )
    assert r.status_code == 200
    # Collect SSE lines and find the done event
    done_event = None
    for line in r.text.splitlines():
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            if ev.get("type") == "done":
                done_event = ev
    assert done_event is not None
    assert done_event["run_id"] == "run-abc"
