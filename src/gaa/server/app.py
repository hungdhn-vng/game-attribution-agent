"""FastAPI app for the GAA Custom Agent (port 8080).

Routes (auth in §7 of the spec):
  POST /chat                  Bearer-gated. SSE stream of the agent loop.
  POST /invocations           Bearer-gated. Structured single-action dispatch.
  GET  /runs/<id>/<artifact>  open, read-only, allowlisted, traversal-safe.
  GET  /health                open.
On startup: persist.restore(ctx) then persona.ensure_seeded(ctx).
"""
from __future__ import annotations

import hmac
import json
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

from gaa.cli.wiring import build_context
from gaa.core.llm.client import LangChainMaaSLLM
from gaa.server import actions, persona
from gaa.server import capabilities  # noqa: F401  (registers exec/browse/self_edit)
from gaa.server.agent import ChatAgent
from gaa import persist

_ARTIFACTS = {"report.html", "summary.md", "activity.log", "ledger.jsonl", "job.json"}
_CONTENT_TYPES = {
    "report.html": "text/html",
    "summary.md": "text/markdown",
    "activity.log": "text/plain",
    "ledger.jsonl": "application/x-ndjson",
    "job.json": "application/json",
}


def _const_eq(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


def create_app(ctx=None, chat_llm=None) -> FastAPI:
    app = FastAPI(title="GAA Custom Agent")
    state = {"ctx": ctx, "chat_llm": chat_llm}

    def get_ctx():
        if state["ctx"] is None:
            state["ctx"] = build_context()
        return state["ctx"]

    def get_chat_llm():
        if state["chat_llm"] is None:
            state["chat_llm"] = LangChainMaaSLLM(get_ctx().settings)
        return state["chat_llm"]

    def require_token(request: Request):
        if not _const_eq(_bearer(request), os.environ.get("GAA_AGENT_TOKEN")):
            raise HTTPException(status_code=401, detail="missing or invalid agent token")

    @app.on_event("startup")
    def _startup():
        c = get_ctx()
        try:
            persist.restore(c)
        except Exception:
            pass
        persona.ensure_seeded(c)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/chat")
    def chat(request: Request, body: dict):
        require_token(request)
        is_admin = _const_eq(request.headers.get("x-gaa-admin-key"),
                             os.environ.get("GAA_ADMIN_KEY"))
        messages = body.get("messages", [])
        agent = ChatAgent(get_ctx(), get_chat_llm())

        def sse():
            try:
                for event in agent.run(messages, is_admin=is_admin):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception:
                # Belt-and-suspenders: never end the stream without a terminal event.
                yield f"data: {json.dumps({'type': 'done', 'run_id': None, 'error': 'internal error'})}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.post("/invocations")
    def invocations(request: Request, body: dict):
        require_token(request)
        is_admin = _const_eq(body.get("admin_key"), os.environ.get("GAA_ADMIN_KEY"))
        result = actions.dispatch(get_ctx(), body.get("action", ""),
                                  body.get("args", {}) or {}, is_admin=is_admin)
        if (body.get("action") in actions.MUTATING_ACTIONS
                and isinstance(result, dict) and result.get("status") == "success"):
            try:
                persist.snapshot(get_ctx())
            except Exception:
                pass
        return JSONResponse(result)

    @app.get("/runs/{run_id}/{artifact}")
    def artifact(run_id: str, artifact: str):
        if artifact not in _ARTIFACTS:
            raise HTTPException(status_code=404, detail="unknown artifact")
        run_dir = get_ctx().runs.path_for(run_id).resolve()
        path = (run_dir / artifact).resolve()
        if not str(path).startswith(str(run_dir) + os.sep) or not path.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(str(path), media_type=_CONTENT_TYPES[artifact])

    return app


# Production ASGI entrypoint (lazy ctx built on first request / startup).
app = create_app()
