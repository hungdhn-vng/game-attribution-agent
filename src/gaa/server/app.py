"""FastAPI front door for the GAA-on-OpenClaw Custom Agent (port 8080).

Routes:
  GET  /health                open; 200 iff front door is up (OpenClaw readiness added in Phase E).
  GET  /runs/<id>/<artifact>  open, read-only, allowlisted, traversal-safe (UNCHANGED).
  POST /chat                  Bearer-gated SSE shim to OpenClaw (Task C3).
  POST /upload                Bearer-gated CSV onboarding (Task C4).
On startup: persist.restore(ctx) (best-effort)."""
from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse

from gaa.cli.wiring import build_context
from gaa import persist

_ARTIFACTS = {"report.html", "summary.md", "activity.log", "ledger.jsonl", "job.json"}
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


def _safe(events):
    try:
        yield from events
    except Exception:
        yield {"type": "done", "run_id": None, "error": "internal error"}


def _onboard_from_csv(ctx, path: str) -> dict:
    from gaa.server import actions
    proposed = actions.dispatch(ctx, "onboard_propose", {"csv": path}, is_admin=False)
    if proposed.get("status") != "success":
        return proposed
    return actions.dispatch(ctx, "onboard_confirm", {}, is_admin=False)


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
        try:
            persist.restore(get_ctx())
        except Exception:
            pass
        yield

    app = FastAPI(title="GAA Front Door", lifespan=lifespan)
    app.state.get_ctx = get_ctx
    app.state.require_token = require_token

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/runs/{run_id}/{artifact}")
    def artifact(run_id: str, artifact: str):
        if artifact not in _ARTIFACTS:
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

    def get_openclaw():
        client = getattr(app.state, "openclaw", None)
        if client is None:
            from gaa.server.openclaw_client import RealOpenClawClient  # Task C5
            client = RealOpenClawClient()
            app.state.openclaw = client
        return client

    @app.post("/chat")
    def chat(request: Request, body: dict):
        require_token(request)
        is_admin = _const_eq(request.headers.get("x-gaa-admin-key"),
                             os.environ.get("GAA_ADMIN_KEY"))
        from fastapi.responses import StreamingResponse
        from gaa.server import shim as _shim
        events = get_openclaw().stream_chat(
            messages=body.get("messages", []), is_admin=is_admin,
            active_run_id=body.get("active_run_id") or None)
        return StreamingResponse(_shim.sse_events(_safe(events)),
                                 media_type="text/event-stream")

    @app.post("/upload")
    async def upload(request: Request, file=None):
        require_token(request)
        import tempfile
        from fastapi import UploadFile, File
        from fastapi.responses import JSONResponse
        # Re-read the file from the request
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            raise HTTPException(status_code=422, detail="file field required")
        data = await upload_file.read()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        return JSONResponse(_onboard_from_csv(get_ctx(), path))

    return app


app = create_app()
