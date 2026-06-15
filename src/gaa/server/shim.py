"""Translate OpenClawClient events into the frontend's SSE contract, and inject the
analyze run_id into the terminal `done` event (robust to the model not echoing it)."""
from __future__ import annotations

import json
from typing import Iterable, Iterator


def sse_events(events: Iterable[dict]) -> Iterator[str]:
    latched_run_id = None
    saw_done = False
    for ev in events:
        if ev.get("type") == "tool_result" and ev.get("tool") == "analyze" and ev.get("run_id"):
            latched_run_id = ev["run_id"]
        if ev.get("type") == "done":
            saw_done = True
            ev = {**ev, "run_id": ev.get("run_id") or latched_run_id}
        yield f"data: {json.dumps(ev)}\n\n"
    if not saw_done:  # never end the stream without a terminal event
        yield f"data: {json.dumps({'type': 'done', 'run_id': latched_run_id})}\n\n"
