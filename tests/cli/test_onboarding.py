import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.profile_store import ProfileStore
from gaa.core.store.metrics_store import MetricsStore


_MAPPING_PRESET = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}


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


def test_onboard_propose_returns_mapping(tmp_path):
    csv = _write_csv(tmp_path)
    resp = _run(["onboard", "propose", "--csv", csv], FakeLLM(_MAPPING_PRESET), tmp_path)
    assert resp["status"] == "success"
    assert resp["mapping"]["date_col"] == "day"
    assert resp["mapping"]["metric_cols"] == {"dau": "dau"}
    assert "message" in resp


def test_onboard_confirm_persists_and_activates(tmp_path):
    csv = _write_csv(tmp_path)
    mapping_json = json.dumps(_MAPPING_PRESET)
    resp = _run(
        ["onboard", "confirm", "--csv", csv, "--mapping", mapping_json,
         "--name", "MyGame", "--platform", "roblox", "--genre", "survival"],
        FakeLLM(_MAPPING_PRESET), tmp_path,
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
    mapping_json = json.dumps(_MAPPING_PRESET)
    _run(
        ["onboard", "confirm", "--csv", csv, "--mapping", mapping_json,
         "--name", "MyGame", "--platform", "roblox", "--genre", "survival"],
        FakeLLM(_MAPPING_PRESET), tmp_path,
    )
    df = MetricsStore(os.environ["GAA_CACHE_DIR"] + "/metrics").load("MyGame")
    assert df["region"].isna().sum() == 0, "no region should be lost to NA-token parsing"
    assert "NA" in set(df["region"]), "the 'NA' region must be preserved, not parsed as NaN"


def test_onboard_confirm_bad_mapping_is_error(tmp_path):
    csv = _write_csv(tmp_path)
    resp = _run(
        ["onboard", "confirm", "--csv", csv, "--mapping", "{not json}",
         "--name", "X", "--platform", "p", "--genre", "g"],
        FakeLLM(_MAPPING_PRESET), tmp_path,
    )
    assert resp["status"] == "error"
