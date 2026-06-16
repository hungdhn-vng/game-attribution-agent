import os
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_ADMIN_KEY", "secret-admin")
    monkeypatch.setenv("GAA_AGENT_TOKEN", "tok")
    monkeypatch.setenv("OPENCLAW_URL_NONADMIN", "http://nonadmin:1")
    monkeypatch.setenv("OPENCLAW_URL_ADMIN", "http://admin:2")
    from gaa.server.app import create_app
    app = create_app()
    return app


def test_chat_routes_to_admin_url_when_admin(monkeypatch, tmp_path):
    app = _client(monkeypatch, tmp_path)
    seen = {}

    class Fake:
        def __init__(self, url): self.url = url
        def stream_chat(self, **kw):
            seen["url"] = self.url
            yield {"type": "done", "run_id": None}

    app.state.openclaw = Fake("nonadmin")          # existing name = non-admin (keeps old tests working)
    app.state.openclaw_admin = Fake("admin")
    c = TestClient(app)
    c.post("/chat", json={"messages": []},
           headers={"authorization": "Bearer tok", "x-gaa-admin-key": "secret-admin"})
    assert seen["url"] == "admin"
    c.post("/chat", json={"messages": []},
           headers={"authorization": "Bearer tok", "x-gaa-admin-key": "wrong"})
    assert seen["url"] == "nonadmin"
