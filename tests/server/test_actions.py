import json
import pandas as pd
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import actions

_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {"main_story": "DAU fell.", "rationale": "SEA drop.",
          "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
          "assumptions_and_gaps": []}


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def test_unknown_action(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    r = actions.dispatch(ctx, "nope", {}, is_admin=False)
    assert r["status"] == "error" and "unknown action" in r["error"]


def test_admin_action_refused_without_admin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    r = actions.dispatch(ctx, "config_set", {"key": "benchmark_mode", "value": "crawl"}, is_admin=False)
    assert r["status"] == "error" and "admin" in r["error"].lower()


def test_admin_action_allowed_with_admin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    r = actions.dispatch(ctx, "config_set", {"key": "benchmark_mode", "value": "crawl"}, is_admin=True)
    assert r["status"] == "success"


def test_analyze_dispatch_returns_run_id(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    # onboard a game first (admin)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    actions.dispatch(ctx, "onboard_confirm",
                     {"csv": str(csv), "mapping": json.dumps(_MAPPING), "name": "G",
                      "platform": "roblox", "genre": "survival"}, is_admin=True)
    r = actions.dispatch(ctx, "analyze", {"query": "why did dau drop?", "budget": "0"}, is_admin=False)
    assert "run_id" in r


def test_base_set_classification():
    # Only the base sets defined in actions.py itself — capability actions (exec/browse/
    # self_edit) are registered by capabilities.py in a LATER task, so are NOT asserted here.
    assert "config_set" in actions.MUTATING_ACTIONS
    assert "analyze" not in actions.MUTATING_ACTIONS
    assert "config_set" in actions.ADMIN_ACTIONS
    assert "doctor" not in actions.ADMIN_ACTIONS


def test_status_accepts_run_alias(tmp_path, monkeypatch):
    # The agent passes `run` (per the tool guide) but _cmd_status reads `run_id`;
    # dispatch must alias run -> run_id so status/step still resolve the run.
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    actions.dispatch(ctx, "onboard_confirm",
                     {"csv": str(csv), "mapping": json.dumps(_MAPPING), "name": "G",
                      "platform": "roblox", "genre": "survival"}, is_admin=True)
    started = actions.dispatch(ctx, "analyze",
                               {"query": "why did dau drop?", "budget": "0"}, is_admin=False)
    rid = started["run_id"]
    r = actions.dispatch(ctx, "status", {"run": rid}, is_admin=False)
    assert r.get("run_id") == rid
    assert r["status"] in ("running", "done")
