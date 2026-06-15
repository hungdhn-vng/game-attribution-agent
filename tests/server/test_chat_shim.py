import json
from gaa.server.shim import sse_events


def _parse(stream):
    return [json.loads(line[6:]) for line in stream if line.startswith("data: ")]


def test_done_run_id_injected_from_analyze_result():
    events = [
        {"type": "activity", "text": "analyzing"},
        {"type": "tool_result", "tool": "analyze", "run_id": "run-7"},
        {"type": "token", "text": "done"},
        {"type": "done", "run_id": None},
    ]
    out = _parse(sse_events(events))
    assert out[-1] == {"type": "done", "run_id": "run-7"}


def test_done_always_terminal_even_on_empty():
    out = _parse(sse_events([]))
    assert out[-1]["type"] == "done"
