"""Hand a built ST request to the browser (which can reach ST) and block for its result.
Cross-process via two sidecar files; the front-door emits the st_request SSE event from the
pending sidecar and writes the result sidecar from POST /sensor-tower/fulfill."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def _req_path() -> str:
    return os.environ.get("GAA_ST_REQUEST") or str(
        Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower" / "st_request.json")


def _res_path() -> str:
    return os.environ.get("GAA_ST_RESULT") or str(
        Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower" / "st_result.json")


def request(built: dict, *, timeout: float = 120.0, poll: float = 0.3, now_fn=time.time) -> dict:
    req_id = uuid.uuid4().hex
    rp = Path(_req_path()); rp.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(rp) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"req_id": req_id, "st_tool": built["st_tool"], "params": built["params"]}, f)
    os.replace(tmp, str(rp))

    deadline = now_fn() + timeout
    res = Path(_res_path())
    while now_fn() < deadline:
        try:
            rec = json.loads(res.read_text())
        except (OSError, ValueError):
            rec = None
        if rec and rec.get("req_id") == req_id:
            if "result" in rec:
                return {"result": rec["result"]}
            return {"error": rec.get("error") or {"kind": "upstream_error"}}
        time.sleep(poll)
    return {"error": {"kind": "fulfill_timeout"}}
