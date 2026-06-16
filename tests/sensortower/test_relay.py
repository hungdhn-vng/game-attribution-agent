import json, threading, time
from pathlib import Path
from gaa.sensortower import relay

def _paths(tmp_path, monkeypatch):
    req = tmp_path / "st_request.json"; res = tmp_path / "st_result.json"
    monkeypatch.setenv("GAA_ST_REQUEST", str(req)); monkeypatch.setenv("GAA_ST_RESULT", str(res))
    return req, res

def test_request_returns_matching_result(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    def fake_browser():
        for _ in range(200):
            if req.exists():
                rid = json.loads(req.read_text())["req_id"]
                res.write_text(json.dumps({"req_id": rid, "result": {"v": 9}}))
                return
            time.sleep(0.01)
    t = threading.Thread(target=fake_browser); t.start()
    out = relay.request({"st_tool": "x", "params": {}}, timeout=5, poll=0.02)
    t.join()
    assert out == {"result": {"v": 9}}

def test_request_maps_error(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    def fake_browser():
        for _ in range(200):
            if req.exists():
                rid = json.loads(req.read_text())["req_id"]
                res.write_text(json.dumps({"req_id": rid, "error": {"kind": "not_connected"}}))
                return
            time.sleep(0.01)
    t = threading.Thread(target=fake_browser); t.start()
    out = relay.request({"st_tool": "x", "params": {}}, timeout=5, poll=0.02)
    t.join()
    assert out == {"error": {"kind": "not_connected"}}

def test_timeout(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    out = relay.request({"st_tool": "x", "params": {}}, timeout=0.2, poll=0.02)
    assert out == {"error": {"kind": "fulfill_timeout"}}

def test_stale_result_ignored(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    res.write_text(json.dumps({"req_id": "OLD", "result": {"stale": True}}))
    out = relay.request({"st_tool": "x", "params": {}}, timeout=0.2, poll=0.02)
    assert out == {"error": {"kind": "fulfill_timeout"}}

def test_pending_sidecar_written(tmp_path, monkeypatch):
    req, res = _paths(tmp_path, monkeypatch)
    # don't fulfill; just check the pending request was written with the built payload
    relay.request({"st_tool": "app_x", "params": {"app_id": [1]}}, timeout=0.1, poll=0.02)
    rec = json.loads(req.read_text())
    assert rec["st_tool"] == "app_x" and rec["params"] == {"app_id": [1]} and rec["req_id"]
