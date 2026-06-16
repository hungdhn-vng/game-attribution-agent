import json
from gaa.server.openclaw_client import RealOpenClawClient

def test_emits_st_request_when_sidecar_appears(tmp_path, monkeypatch):
    req = tmp_path / "st_request.json"
    monkeypatch.setenv("GAA_ST_REQUEST", str(req))
    req.write_text(json.dumps({"req_id": "R1", "st_tool": "t", "params": {"a": 1}}))
    c = RealOpenClawClient(url="http://127.0.0.1:9", progress="")  # unreachable → reader errors fast
    seen = []
    try:
        for ev in c.stream_chat(messages=[{"role": "user", "content": "hi"}], is_admin=False, active_run_id=None):
            seen.append(ev)
    except Exception:
        pass
    st = [e for e in seen if e.get("type") == "st_request"]
    assert st and st[0]["req_id"] == "R1" and st[0]["st_tool"] == "t" and st[0]["params"] == {"a": 1}

def test_emits_each_req_id_once(tmp_path, monkeypatch):
    # Directly exercise the poller method to assert dedup, independent of the HTTP reader.
    import queue, threading
    req = tmp_path / "st_request.json"
    monkeypatch.setenv("GAA_ST_REQUEST", str(req))
    req.write_text(json.dumps({"req_id": "R1", "st_tool": "t", "params": {}}))
    c = RealOpenClawClient(url="http://127.0.0.1:9", progress="")
    q: queue.Queue = queue.Queue()
    stop = threading.Event()
    t = threading.Thread(target=c._poll_st_request, args=(q, stop), daemon=True)
    t.start()
    # wait for first emit
    import time
    first = q.get(timeout=2)
    # same req_id should NOT be re-emitted
    stop.set(); t.join(timeout=2)
    assert first["req_id"] == "R1"
    assert q.empty()  # no duplicate emit for the unchanged req_id
