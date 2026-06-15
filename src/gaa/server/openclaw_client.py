"""Boundary to the OpenClaw runtime. The concrete client (Task C5) speaks the transport
recorded in Spike A4; the shim (Task C3) and tests depend only on this interface."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterator, Protocol

import httpx


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
    """Drives an OpenClaw chat turn over HTTP /v1/chat/completions (stream) and surfaces
    the analyze run_id via the shared-FS sidecar (HTTP completions hides MCP tool results)."""

    def __init__(self, *, url: str | None = None, token: str | None = None, sidecar: str | None = None):
        self._url = (url or os.environ.get("OPENCLAW_URL", "http://127.0.0.1:18789")).rstrip("/")
        self._token = token or os.environ.get("OPENCLAW_TOKEN", "")
        self._sidecar = sidecar or os.environ.get("GAA_RUN_SIDECAR", "")

    def stream_chat(self, *, messages, is_admin, active_run_id) -> Iterator[dict]:
        start = time.time()
        body = {"model": "openclaw", "messages": messages, "stream": True,
                "user": active_run_id or "default"}
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        with httpx.stream("POST", f"{self._url}/v1/chat/completions",
                          json=body, headers=headers, timeout=300.0) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    yield {"type": "token", "text": text}
        rid = self._run_since(start)
        if rid:
            yield {"type": "tool_result", "tool": "analyze", "run_id": rid}
        yield {"type": "done", "run_id": None}

    def _run_since(self, start: float):
        if not self._sidecar:
            return None
        try:
            rec = json.loads(Path(self._sidecar).read_text())
        except (OSError, ValueError):
            return None
        # accept a small clock skew window
        if rec.get("run_id") and rec.get("ts", 0) >= start - 2:
            return rec["run_id"]
        return None
