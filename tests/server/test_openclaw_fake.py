from gaa.server.openclaw_client import FakeOpenClawClient


def test_fake_yields_scripted_events():
    c = FakeOpenClawClient([
        {"type": "activity", "text": "analyzing"},
        {"type": "tool_result", "tool": "analyze", "run_id": "run-7"},
        {"type": "token", "text": "Revenue dropped because..."},
        {"type": "done", "run_id": None},
    ])
    evs = list(c.stream_chat(messages=[{"role": "user", "content": "why?"}],
                             is_admin=False, active_run_id=None))
    assert evs[1]["run_id"] == "run-7"
    assert evs[-1]["type"] == "done"
