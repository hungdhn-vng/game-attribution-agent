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
    monkeypatch.setattr(appmod, "_onboard_from_upload",
                        lambda ctx, content_b64, **kw: calls.append(content_b64) or {"status": "success", "run_id": "r1"})
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", headers={"Authorization": "Bearer secret"},
                    files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert len(calls) == 1


def test_upload_snapshots_on_success(monkeypatch):
    """A successful onboard must trigger persist.snapshot so the new profile is durable."""
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    import gaa.server.app as appmod
    snapshot_calls = []
    monkeypatch.setattr(appmod, "_onboard_from_upload",
                        lambda ctx, content_b64, **kw: {"status": "success", "run_id": "r1"})
    monkeypatch.setattr(appmod.persist, "snapshot", lambda ctx: snapshot_calls.append(ctx) or True)
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", headers={"Authorization": "Bearer secret"},
                    files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 200
    assert len(snapshot_calls) == 1


def test_upload_no_snapshot_on_failure(monkeypatch):
    """A failed onboard must NOT trigger persist.snapshot."""
    monkeypatch.setenv("GAA_AGENT_TOKEN", "secret")
    import gaa.server.app as appmod
    snapshot_calls = []
    monkeypatch.setattr(appmod, "_onboard_from_upload",
                        lambda ctx, content_b64, **kw: {"status": "error", "error": "bad csv"})
    monkeypatch.setattr(appmod.persist, "snapshot", lambda ctx: snapshot_calls.append(ctx) or True)
    client = TestClient(create_app(ctx=object()))
    r = client.post("/upload", headers={"Authorization": "Bearer secret"},
                    files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 200
    assert len(snapshot_calls) == 0
