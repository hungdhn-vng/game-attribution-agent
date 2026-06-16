"""FastAPI front door for the GAA-on-OpenClaw Custom Agent (port 8080).

Routes:
  GET  /health                open; 200 iff front door is up (OpenClaw readiness added in Phase E).
  GET  /runs/<id>/<artifact>  open, read-only, allowlisted, traversal-safe (UNCHANGED).
  POST /chat                  Bearer-gated SSE shim to OpenClaw (Task C3).
  POST /upload                Bearer-gated CSV onboarding (Task C4).
  POST /sensor-tower/callback Bearer-gated; frontend relays an O365 OAuth code to exchange for tokens.
  POST /sensor-tower/fulfill  Bearer-gated; frontend posts the browser-fetched ST result → result sidecar.
On startup: nothing (restore is done by the container entrypoint before the gateway boots)."""
from __future__ import annotations

import hmac
import json
import logging
import os
import tempfile
import time as _time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from gaa.cli.wiring import build_context
from gaa import persist
from gaa.server import actions
from gaa.server import shim as _shim
from gaa.server.openclaw_client import RealOpenClawClient

_log = logging.getLogger(__name__)


def _st_result_path() -> str:
    return os.environ.get("GAA_ST_RESULT") or os.path.join(
        os.environ.get("GAA_CACHE_DIR", "data/cache"), "sensortower", "st_result.json")


def _st_exchange_code(code: str, state: str, *, now: float) -> dict:
    from gaa.sensortower import oauth
    return oauth.exchange_code(code, state, now=now)


_CONTENT_TYPES = {
    "report.html": "text/html", "summary.md": "text/markdown",
    "activity.log": "text/plain", "ledger.jsonl": "application/x-ndjson",
    "job.json": "application/json",
}


def _const_eq(a: str | None, b: str | None) -> bool:
    return bool(a and b and hmac.compare_digest(a, b))


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


def _safe(events) -> None:
    try:
        yield from events
    except Exception:
        _log.exception("openclaw stream_chat raised; injecting terminal done")
        yield {"type": "done", "run_id": None, "error": "internal error"}


def _onboard_from_csv(ctx, path: str, *, name: str = "uploaded_game",
                      platform: str = "generic", genre: str = "casual",
                      adapter: str = "generic") -> dict:
    import json as _json
    proposed = actions.dispatch(ctx, "onboard_propose", {"csv": path, "adapter": adapter},
                                is_admin=False)
    if proposed.get("status") != "success":
        return proposed
    mapping_json = _json.dumps(proposed["mapping"])
    return actions.dispatch(ctx, "onboard_confirm",
                            {"csv": path, "mapping": mapping_json,
                             "name": name, "platform": platform,
                             "genre": genre, "adapter": adapter},
                            is_admin=False)


def create_app(ctx=None) -> FastAPI:
    state = {"ctx": ctx}

    def get_ctx():
        if state["ctx"] is None:
            state["ctx"] = build_context()
        return state["ctx"]

    def require_token(request: Request):
        if not _const_eq(_bearer(request), os.environ.get("GAA_AGENT_TOKEN")):
            raise HTTPException(status_code=401, detail="missing or invalid agent token")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="GAA Front Door", lifespan=lifespan)
    # Construction must stay cheap; Task C5 connects lazily on first stream_chat.
    app.state.openclaw = RealOpenClawClient(
        url=os.environ.get("OPENCLAW_URL_NONADMIN", "http://127.0.0.1:18789"))
    app.state.openclaw_admin = RealOpenClawClient(
        url=os.environ.get("OPENCLAW_URL_ADMIN", "http://127.0.0.1:18790"))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/runs/{run_id}/{artifact}")
    def artifact(run_id: str, artifact: str):
        if artifact not in _CONTENT_TYPES:
            raise HTTPException(status_code=404, detail="unknown artifact")
        runs = get_ctx().runs
        runs_root = runs.path_for("__root_probe__").parent.resolve()
        run_dir = runs.path_for(run_id).resolve()
        if run_dir.parent != runs_root:
            raise HTTPException(status_code=404, detail="not found")
        path = (run_dir / artifact).resolve()
        if path.parent != run_dir or not path.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(str(path), media_type=_CONTENT_TYPES[artifact])

    @app.post("/chat")
    def chat(request: Request, body: dict | None = None):
        require_token(request)
        body = body or {}
        is_admin = _const_eq(request.headers.get("x-gaa-admin-key"),
                             os.environ.get("GAA_ADMIN_KEY"))
        client = app.state.openclaw_admin if is_admin else app.state.openclaw
        events = client.stream_chat(
            messages=body.get("messages", []), is_admin=is_admin,
            active_run_id=body.get("active_run_id") or None)
        return StreamingResponse(
            _shim.sse_events(_safe(events)),
            media_type="text/event-stream",
            # Defeat proxy/ingress buffering so tokens + activity arrive live, not
            # in one burst at the end (X-Accel-Buffering disables nginx buffering).
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/upload")
    async def upload(request: Request):
        require_token(request)
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            raise HTTPException(status_code=422, detail="file field required")
        data = await upload_file.read()
        # Derive a game name from the uploaded filename (stem only, no extension)
        original_name = getattr(upload_file, "filename", None) or "uploaded_game"
        game_name = os.path.splitext(original_name)[0].replace(" ", "_") or "uploaded_game"
        platform = form.get("platform", "generic")
        genre = form.get("genre", "casual")
        adapter = form.get("adapter", "generic")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        try:
            result = _onboard_from_csv(get_ctx(), path,
                                       name=game_name, platform=platform,
                                       genre=genre, adapter=adapter)
            if isinstance(result, dict) and result.get("status") == "success":
                try:
                    persist.snapshot(get_ctx())
                except Exception:
                    _log.exception("vStorage snapshot after /upload failed")
        finally:
            os.unlink(path)
        return JSONResponse(result)

    @app.post("/sensor-tower/callback")
    def sensor_tower_callback(request: Request, body: dict | None = None):
        require_token(request)
        body = body or {}
        code, state = body.get("code"), body.get("state")
        if not code or not state:
            raise HTTPException(status_code=422, detail="code and state required")
        try:
            _st_exchange_code(code, state, now=_time.time())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            _log.exception("sensor tower code exchange failed")
            raise HTTPException(status_code=502, detail="token exchange failed")
        try:
            persist.snapshot(get_ctx())
        except Exception:
            _log.exception("vStorage snapshot after sensor-tower connect failed")
        return JSONResponse({"status": "success"})

    @app.post("/sensor-tower/fulfill")
    def sensor_tower_fulfill(request: Request, body: dict | None = None):
        require_token(request)
        body = body or {}
        if not body.get("req_id") or ("result" not in body and "error" not in body):
            raise HTTPException(status_code=422, detail="req_id and result|error required")
        path = _st_result_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        rec = {"req_id": body["req_id"]}
        if "result" in body:
            rec["result"] = body["result"]
        else:
            rec["error"] = body["error"]
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, path)
        return JSONResponse({"status": "success"})

    return app


app = create_app()
