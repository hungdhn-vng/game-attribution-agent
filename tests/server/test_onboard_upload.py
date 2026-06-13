import base64, json
import pandas as pd
from types import SimpleNamespace
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.cli.commands.onboarding import cmd_onboard_propose, cmd_onboard_confirm

_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_CSV = "day,region,dau\n2026-05-01,SEA,1000\n2026-05-03,SEA,400\n"
_B64 = base64.b64encode(_CSV.encode()).decode()


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def test_propose_accepts_csv_b64(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _MAPPING)  # FakeLLM returns the mapping for profiler.propose
    args = SimpleNamespace(csv=None, csv_b64=_B64, adapter="generic")
    r = cmd_onboard_propose(ctx, args)
    assert r["status"] == "success" and "mapping" in r


def test_confirm_accepts_csv_b64(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    args = SimpleNamespace(csv=None, csv_b64=_B64, mapping=json.dumps(_MAPPING),
                           name="G", platform="roblox", genre="survival", adapter="generic")
    r = cmd_onboard_confirm(ctx, args)
    assert r["status"] == "success" and r["row_count"] == 2 and "dau" in r["metrics"]
