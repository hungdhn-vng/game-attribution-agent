import json
import pandas as pd
from fastapi.testclient import TestClient
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server.app import create_app
from gaa.server import persona

_SYNTH = {"main_story": "DAU fell.", "rationale": "x",
          "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
          "assumptions_and_gaps": []}


class ScriptedLLM:
    def __init__(self, script): self._s = list(script)
    def complete_json(self, system, user): return self._s.pop(0)


def _client(tmp_path, monkeypatch, *, chat_llm=None, preset=_SYNTH, token="t0k", admin="adm"):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    monkeypatch.setenv("GAA_AGENT_TOKEN", token)
    monkeypatch.setenv("GAA_ADMIN_KEY", admin)
    ctx = build_context(llm=FakeLLM(preset), today="2026-06-13")
    persona.ensure_seeded(ctx)
    app = create_app(ctx=ctx, chat_llm=chat_llm)
    return TestClient(app), ctx


def test_health_open(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200


def test_chat_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, chat_llm=ScriptedLLM([{"final": "hi"}]))
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


def test_chat_streams_with_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, chat_llm=ScriptedLLM([{"final": "hello there"}]))
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]},
                    headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 200
    assert "hello there" in r.text  # SSE body contains the streamed tokens


def test_invocations_dispatch(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    r = client.post("/invocations", json={"action": "doctor", "args": {}},
                    headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 200
    assert r.json()["status"] in ("success", "error")  # doctor returns a status


def test_invocations_admin_action_needs_key(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = {"action": "config_set", "args": {"key": "benchmark_mode", "value": "crawl"}}
    r1 = client.post("/invocations", json=body, headers={"Authorization": "Bearer t0k"})
    assert r1.json()["status"] == "error"  # no admin key
    r2 = client.post("/invocations", json={**body, "admin_key": "adm"},
                     headers={"Authorization": "Bearer t0k"})
    assert r2.json()["status"] == "success"


def test_artifact_route_serves_and_blocks_traversal(tmp_path, monkeypatch):
    client, ctx = _client(tmp_path, monkeypatch)
    # create a run dir with a report.html
    run = ctx.runs.create(session="s", query="why", suffix="aaaa")
    (ctx.runs.path_for(run.run_id) / "report.html").write_text("<html>dossier</html>")
    ok = client.get(f"/runs/{run.run_id}/report.html")
    assert ok.status_code == 200 and "dossier" in ok.text
    # traversal / disallowed artifact name
    bad = client.get(f"/runs/{run.run_id}/../../etc/passwd")
    assert bad.status_code in (400, 404)
    bad2 = client.get(f"/runs/{run.run_id}/secret.txt")
    assert bad2.status_code == 404  # not in the artifact allowlist
