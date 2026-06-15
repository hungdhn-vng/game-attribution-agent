"""Translate OpenClawClient events into the frontend's SSE contract, and inject the
analyze run_id into the terminal `done` event (robust to the model not echoing it)."""
from __future__ import annotations

import json
import logging
from typing import Iterable, Iterator

_log = logging.getLogger(__name__)


def sse_events(events: Iterable[dict]) -> Iterator[str]:
    latched_run_id = None
    saw_done = False
    for ev in events:
        if ev.get("type") == "tool_result" and ev.get("tool") == "analyze" and ev.get("run_id"):
            latched_run_id = ev["run_id"]
        if ev.get("type") == "done":
            saw_done = True
            ev = {**ev, "run_id": ev.get("run_id") or latched_run_id}
        try:
            yield f"data: {json.dumps(ev)}\n\n"
        except (TypeError, ValueError):
            _log.exception("event not JSON-serializable: %r", ev)
            yield f"data: {json.dumps({'type': 'done', 'run_id': latched_run_id, 'error': 'serialization error'})}\n\n"
            return
    if not saw_done:  # never end the stream without a terminal event
        yield f"data: {json.dumps({'type': 'done', 'run_id': latched_run_id})}\n\n"
