"""Boundary to the OpenClaw runtime. The concrete client (Task C5) speaks the transport
recorded in Spike A4; the shim (Task C3) and tests depend only on this interface."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Iterator, Protocol

import httpx

_SENTINEL = object()  # marks end-of-stream on the internal queue


def _read_complete_lines(path: str) -> list[str]:
    """Return only newline-terminated lines from *path* (drops a partial trailing
    line still being appended). Missing/unreadable file → []."""
    try:
        with open(path, "r") as f:
            data = f.read()
    except OSError:
        return []
    if not data:
        return []
    return data.split("\n")[:-1]


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

    def __init__(self, *, url: str | None = None, token: str | None = None,
                 sidecar: str | None = None, progress: str | None = None,
                 progress_interval: float = 0.4):
        self._url = (url or os.environ.get("OPENCLAW_URL", "http://127.0.0.1:18789")).rstrip("/")
        self._token = token or os.environ.get("OPENCLAW_TOKEN", "")
        self._sidecar = sidecar or os.environ.get("GAA_RUN_SIDECAR", "")
        # Progress sidecar the analyze pipeline appends per stage; tailed here to
        # narrate activity during the dead-air while a server-side tool runs.
        self._progress = progress if progress is not None else os.environ.get("GAA_PROGRESS", "")
        self._progress_interval = progress_interval
        self._st_request = os.environ.get("GAA_ST_REQUEST", "")

    def stream_chat(self, *, messages, is_admin, active_run_id) -> Iterator[dict]:
        start = time.time()
        body = {"model": "openclaw", "messages": messages, "stream": True,
                "user": active_run_id or "default"}
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

        # The HTTP completion stream is dead-air while OpenClaw runs a server-side
        # tool, then bursts the answer tokens. To narrate GAA progress during that
        # gap we read the stream and tail the progress sidecar on two threads, both
        # feeding one queue this generator yields from (tokens + activity interleaved).
        q: queue.Queue = queue.Queue()
        stop = threading.Event()
        err: list[Exception] = []

        # Capture the sidecar's current line count BEFORE work starts so only THIS
        # turn's progress is narrated (prior turns' lines are gated out).
        progress_start = len(_read_complete_lines(self._progress)) if self._progress else 0

        reader = threading.Thread(target=self._read_stream, args=(body, headers, q, err), daemon=True)
        poller = None
        if self._progress:
            poller = threading.Thread(target=self._poll_progress, args=(q, stop, progress_start), daemon=True)
        st_poller = None
        if self._st_request:
            st_poller = threading.Thread(target=self._poll_st_request, args=(q, stop), daemon=True)
        reader.start()
        if poller:
            poller.start()
        if st_poller:
            st_poller.start()

        try:
            while True:
                item = q.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            stop.set()
        if poller:
            poller.join(timeout=1.0)
        if st_poller:
            st_poller.join(timeout=1.0)
        # Drain any straggler activity the poller queued after the answer streamed.
        while not q.empty():
            item = q.get_nowait()
            if item is not _SENTINEL:
                yield item

        if err:
            raise err[0]
        rid = self._run_since(start)
        if rid:
            yield {"type": "tool_result", "tool": "analyze", "run_id": rid}
        yield {"type": "done", "run_id": None}

    def _read_stream(self, body: dict, headers: dict, q: queue.Queue, err: list) -> None:
        try:
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
                        q.put({"type": "token", "text": text})
        except Exception as exc:  # surfaced to the generator after the sentinel
            err.append(exc)
        finally:
            q.put(_SENTINEL)

    def _poll_progress(self, q: queue.Queue, stop: threading.Event, start_index: int) -> None:
        emitted = start_index
        while True:
            lines = _read_complete_lines(self._progress)
            for raw in lines[emitted:]:
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                text = obj.get("text")
                if text:
                    q.put({"type": "activity", "text": text})
            emitted = max(emitted, len(lines))
            if stop.is_set():
                return  # one final read above already happened, then we exit
            stop.wait(self._progress_interval)

    def _poll_st_request(self, q: queue.Queue, stop: threading.Event) -> None:
        last = None
        while True:
            try:
                rec = json.loads(Path(self._st_request).read_text())
            except (OSError, ValueError):
                rec = None
            if rec and rec.get("req_id") and rec["req_id"] != last:
                last = rec["req_id"]
                q.put({"type": "st_request", "req_id": rec["req_id"],
                       "st_tool": rec.get("st_tool"), "params": rec.get("params")})
            if stop.is_set():
                return
            stop.wait(0.3)

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
