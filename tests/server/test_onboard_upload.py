import base64
import json
import io
from types import SimpleNamespace

import pandas as pd

from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.cli.commands.onboarding import cmd_onboard_propose, cmd_onboard_confirm

# FakeLLM returns this plan body for the profiler (read_spec is added from the RawTable)
_PLAN_BODY = {"orientation": "wide", "date_col": "day",
              "metric_cols": {"dau": "dau", "ccu": "ccu"},
              "dim_cols": {"region": "region"}, "confidence": 0.95, "notes": []}
_CSV = "day,region,dau,ccu\n2026-05-01,SEA,1000,200\n2026-05-03,SEA,400,80\n"
_B64 = base64.b64encode(_CSV.encode()).decode()


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def test_propose_returns_plan_and_auto_ok(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _PLAN_BODY)
    args = SimpleNamespace(content_b64=_B64, filename="MyGame.csv")
    r = cmd_onboard_propose(ctx, args)
    assert r["status"] == "success"
    assert r["plan"]["orientation"] == "wide"
    assert r["plan"]["metric_cols"]["ccu"] == "ccu"   # passthrough survives
    assert r["auto_ok"] is True                        # confidence 0.95 ≥ 0.8, no notes
    assert "ccu" in str(r["preview"])


def test_confirm_ingests_via_plan(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    plan = dict(_PLAN_BODY, read_spec={"format": "csv", "delimiter": ",",
                                       "encoding": "utf-8", "header_row": 0})
    args = SimpleNamespace(content_b64=_B64, plan=json.dumps(plan),
                           name="G", platform="roblox", genre="survival")
    r = cmd_onboard_confirm(ctx, args)
    assert r["status"] == "success"
    assert r["row_count"] == 4                          # 2 dates × 2 metrics
    assert set(r["metrics"]) == {"ccu", "dau"}


def test_propose_from_pasted_text(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _PLAN_BODY)
    text = "day\tregion\tdau\tccu\n2026-05-01\tSEA\t1000\t200\n"
    args = SimpleNamespace(text=text)
    r = cmd_onboard_propose(ctx, args)
    assert r["status"] == "success" and r["plan"]["read_spec"]["format"] == "paste"


def test_propose_unreadable_returns_structured_error(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _PLAN_BODY)
    r = cmd_onboard_propose(ctx, SimpleNamespace())
    assert r["status"] == "error" and r["error"] == "unreadable_file"
