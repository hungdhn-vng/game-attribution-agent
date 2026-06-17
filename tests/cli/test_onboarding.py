import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.profile_store import ProfileStore
from gaa.core.store.metrics_store import MetricsStore


# FakeLLM preset returns a plan body (read_spec is injected by Profiler.propose from the RawTable)
_PLAN_PRESET = {
    "orientation": "wide",
    "date_col": "day",
    "metric_cols": {"dau": "dau"},
    "dim_cols": {"region": "region"},
    "confidence": 0.95,
    "notes": [],
}

# Full plan for confirm (includes read_spec since it's passed directly, not via propose)
_PLAN_WITH_SPEC = {
    **_PLAN_PRESET,
    "read_spec": {"format": "csv", "delimiter": ",", "encoding": "utf-8", "header_row": 0},
}


def _write_csv(tmp_path):
    csv = tmp_path / "metrics.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)
    return str(csv)


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")


def _run(argv, llm, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_onboard_propose_returns_plan(tmp_path):
    csv = _write_csv(tmp_path)
    resp = _run(["onboard", "propose", "--csv", csv], FakeLLM(_PLAN_PRESET), tmp_path)
    assert resp["status"] == "success"
    assert resp["plan"]["date_col"] == "day"
    assert resp["plan"]["metric_cols"] == {"dau": "dau"}
    assert resp["auto_ok"] is True          # confidence 0.95 ≥ 0.8, no notes
    assert "summary" in resp


def test_onboard_confirm_persists_and_activates(tmp_path):
    csv = _write_csv(tmp_path)
    plan_json = json.dumps(_PLAN_WITH_SPEC)
    resp = _run(
        ["onboard", "confirm", "--csv", csv, "--plan", plan_json,
         "--name", "MyGame", "--platform", "roblox", "--genre", "survival"],
        FakeLLM(_PLAN_PRESET), tmp_path,
    )
    assert resp["status"] == "success"
    assert resp["name"] == "MyGame"
    assert resp["row_count"] == 4
    assert resp["metrics"] == ["dau"]
    ps = ProfileStore(os.environ["GAA_DB_PATH"])
    assert ps.get_active().name == "MyGame"
    df = MetricsStore(os.environ["GAA_CACHE_DIR"] + "/metrics").load("MyGame")
    assert len(df) == 4


def test_onboard_preserves_na_region(tmp_path):
    # "NA" (North America) must survive ingestion — pandas' default na_values would
    # otherwise parse the string "NA" as NaN and silently null out the region label,
    # excluding North America from every dimensional analysis.
    csv = _write_csv(tmp_path)  # region column includes "NA" rows
    plan_json = json.dumps(_PLAN_WITH_SPEC)
    _run(
        ["onboard", "confirm", "--csv", csv, "--plan", plan_json,
         "--name", "MyGame", "--platform", "roblox", "--genre", "survival"],
        FakeLLM(_PLAN_PRESET), tmp_path,
    )
    df = MetricsStore(os.environ["GAA_CACHE_DIR"] + "/metrics").load("MyGame")
    assert df["region"].isna().sum() == 0, "no region should be lost to NA-token parsing"
    assert "NA" in set(df["region"]), "the 'NA' region must be preserved, not parsed as NaN"


def test_onboard_confirm_bad_plan_is_error(tmp_path):
    csv = _write_csv(tmp_path)
    resp = _run(
        ["onboard", "confirm", "--csv", csv, "--plan", "{not json}",
         "--name", "X", "--platform", "p", "--genre", "g"],
        FakeLLM(_PLAN_PRESET), tmp_path,
    )
    assert resp["status"] == "error"
