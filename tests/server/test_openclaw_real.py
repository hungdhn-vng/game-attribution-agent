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


def test_read_complete_lines_skips_partial_and_missing(tmp_path):
    from gaa.server.openclaw_client import _read_complete_lines
    assert _read_complete_lines(str(tmp_path / "nope.jsonl")) == []
    p = tmp_path / "prog.jsonl"
    p.write_text('{"a":1}\n{"b":2}\n{"partial"')  # last line has no newline yet
    assert _read_complete_lines(str(p)) == ['{"a":1}', '{"b":2}']


def test_emits_activity_from_progress_during_stream(tmp_path, monkeypatch):
    import time as _t
    prog = tmp_path / "progress.jsonl"
    # a line from a PRIOR turn — must be gated out (only this turn's progress narrates)
    prog.write_text(json.dumps({"ts": "t0", "stage": "old", "text": "PRIOR TURN"}) + "\n")

    class _StreamWritesProgress:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass

        def iter_lines(self):
            # the analyze tool advances stages (writing progress) before the answer streams
            with open(prog, "a") as f:
                f.write(json.dumps({"ts": "t1", "stage": "plan", "text": "Scanned metrics"}) + "\n")
                f.write(json.dumps({"ts": "t2", "stage": "synth", "text": "Sampled 3x"}) + "\n")
            _t.sleep(0.15)  # let the poller tick at least once
            for ln in _sse({"choices": [{"delta": {"content": "Answer"}}]}):
                yield ln

    import gaa.server.openclaw_client as mod
    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: _StreamWritesProgress())
    c = RealOpenClawClient(url="http://x", token="t", sidecar="",
                           progress=str(prog), progress_interval=0.02)
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "analyze"}],
                             is_admin=False, active_run_id=None))
    acts = [e["text"] for e in evs if e["type"] == "activity"]
    assert "Scanned metrics" in acts and "Sampled 3x" in acts
    assert "PRIOR TURN" not in acts
    assert any(e["type"] == "token" and e["text"] == "Answer" for e in evs)
    assert evs[-1] == {"type": "done", "run_id": None}


def test_progress_disabled_yields_no_activity(tmp_path, monkeypatch):
    import gaa.server.openclaw_client as mod
    monkeypatch.setattr(mod.httpx, "stream",
                        lambda *a, **k: _FakeStream(_sse({"choices": [{"delta": {"content": "hi"}}]})))
    c = RealOpenClawClient(url="http://x", token="t", sidecar="", progress="")
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "x"}], is_admin=False, active_run_id=None))
    assert not [e for e in evs if e["type"] == "activity"]
    assert evs[-1] == {"type": "done", "run_id": None}
