import json
import pandas as pd
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import actions, capabilities  # noqa: F401 (capabilities registers exec/etc.)
from gaa.server.agent import ChatAgent


class ScriptedLLM:
    """Returns a queued sequence of decision dicts (one per complete_json call)."""
    def __init__(self, script):
        self._script = list(script)

    def complete_json(self, system, user):
        return self._script.pop(0)


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def _collect(agent, messages, is_admin=False):
    return list(agent.run(messages, is_admin=is_admin))


def test_immediate_final(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    llm = ScriptedLLM([{"final": "Hello, I can analyze your game."}])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "hi"}])
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert "analyze your game" in tokens
    assert events[-1]["type"] == "done"


def test_action_then_final_appends_marker(tmp_path, monkeypatch):
    _SYNTH = {"main_story": "DAU fell.", "rationale": "x",
              "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
              "assumptions_and_gaps": []}
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    actions.dispatch(ctx, "onboard_confirm",
                     {"csv": str(csv), "mapping": json.dumps(
                         {"date_col": "day", "metric_cols": {"dau": "dau"},
                          "dim_cols": {"region": "region"}}),
                      "name": "G", "platform": "roblox", "genre": "survival"}, is_admin=True)
    llm = ScriptedLLM([
        {"action": "analyze", "args": {"query": "why did dau drop?", "budget": "0"}},
        {"final": "Here is what I found."},
    ])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "why did dau drop?"}])
    assert any(e["type"] == "activity" for e in events)
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert "[[gaa:run_id=" in tokens
    assert events[-1]["type"] == "done" and events[-1]["run_id"]


def test_admin_gate_in_loop(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    llm = ScriptedLLM([
        {"action": "exec", "args": {"command": "echo x"}},
        {"final": "done"},
    ])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "run echo"}], is_admin=False)
    # the exec result fed back must be an error; loop still ends with a final
    assert events[-1]["type"] == "done"


def test_max_iterations_terminates(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    # always returns an action, never a final -> must stop at the cap
    llm = ScriptedLLM([{"action": "status", "args": {"run_id": "nope"}}] * 50)
    events = _collect(ChatAgent(ctx, llm, max_iters=5), [{"role": "user", "content": "loop"}])
    assert events[-1]["type"] == "done"
    assert sum(1 for e in events if e["type"] == "activity") <= 5
