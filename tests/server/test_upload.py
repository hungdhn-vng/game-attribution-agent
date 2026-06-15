import io
from fastapi.testclient import TestClient
from gaa.server.app import create_app


def test_upload_requires_token(monkeypatch):
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 401


def test_upload_dispatches_onboard(monkeypatch):
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    import gaa.server.app as appmod
    calls = []
    monkeypatch.setattr(appmod, "_onboard_from_csv",
                        lambda ctx, path, **kw: calls.append(path) or {"status": "success", "run_id": "r1"})
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", headers={"Authorization": "Bearer secret"},
                    files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert len(calls) == 1
