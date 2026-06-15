import json
from gaa.server.openclaw_client import RealOpenClawClient


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for ln in self._lines:
            yield ln


def _sse(*chunks):
    out = []
    for c in chunks:
        out.append("data: " + json.dumps(c))
    out.append("data: [DONE]")
    return out


def test_streams_tokens_and_terminal_done(monkeypatch):
    lines = _sse(
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    )
    import gaa.server.openclaw_client as mod
    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: _FakeStream(lines))
    c = RealOpenClawClient(url="http://x", token="t", sidecar="")
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "hi"}], is_admin=False, active_run_id=None))
    assert [e for e in evs if e["type"] == "token"] == [{"type": "token", "text": "Hel"}, {"type": "token", "text": "lo"}]
    assert evs[-1] == {"type": "done", "run_id": None}


def test_emits_tool_result_from_recent_sidecar(tmp_path, monkeypatch):
    import time as _t
    side = tmp_path / "last_run.json"
    side.write_text(json.dumps({"run_id": "run-9", "ts": _t.time() + 0.5}))  # within window
    import gaa.server.openclaw_client as mod
    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: _FakeStream(_sse({"choices": [{"delta": {"content": "done"}}]})))
    c = RealOpenClawClient(url="http://x", token="t", sidecar=str(side))
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "analyze"}], is_admin=False, active_run_id=None))
    tr = [e for e in evs if e["type"] == "tool_result"]
    assert tr == [{"type": "tool_result", "tool": "analyze", "run_id": "run-9"}]


def test_stale_sidecar_ignored(tmp_path, monkeypatch):
    side = tmp_path / "last_run.json"
    side.write_text(json.dumps({"run_id": "old", "ts": 1.0}))  # ancient
    import gaa.server.openclaw_client as mod
    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: _FakeStream(_sse({"choices": [{"delta": {"content": "x"}}]})))
    c = RealOpenClawClient(url="http://x", token="t", sidecar=str(side))
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "x"}], is_admin=False, active_run_id=None))
    assert not [e for e in evs if e["type"] == "tool_result"]
