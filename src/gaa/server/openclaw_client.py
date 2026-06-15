"""Boundary to the OpenClaw runtime. The concrete client (Task C5) speaks the transport
recorded in Spike A4; the shim (Task C3) and tests depend only on this interface."""
from __future__ import annotations

from typing import Iterator, Protocol


class OpenClawClient(Protocol):
    def stream_chat(self, *, messages: list[dict], is_admin: bool,
                    active_run_id: str | None) -> Iterator[dict]:
        """Yield normalized events:
          {"type": "activity", "text": ...}      progress
          {"type": "thinking", "text": ...}      reasoning (optional)
          {"type": "token", "text": ...}         assistant token
          {"type": "tool_result", "tool": ...,   a tool finished; analyze carries run_id
                                   "run_id": ...}
          {"type": "done", "run_id": <id|None>}  terminal
        """
        ...


class FakeOpenClawClient:
    """Scripted client for tests."""
    def __init__(self, events: list[dict]):
        self._events = events

    def stream_chat(self, *, messages, is_admin, active_run_id) -> Iterator[dict]:
        for ev in self._events:
            yield ev


class RealOpenClawClient:
    """Concrete client over the OpenClaw transport — completed in Task C5 (gated on Spike A4)."""
    def stream_chat(self, *, messages, is_admin, active_run_id):
        raise NotImplementedError("RealOpenClawClient pending Spike A4; tests inject app.state.openclaw")
