import json
import os

import pandas as pd

from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.store.profile_store import ProfileStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.runs.store import RunStore


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-03"]),
        "metric": ["dau", "dau"], "value": [1000.0, 400.0], "region": ["SEA", "SEA"],
    })
    for col in ["platform", "version", "cohort", "device", "source"]:
        df[col] = None
    MetricsStore(str(tmp_path / "cache" / "metrics")).save("MyGame", df)
    BenchmarkStore(str(tmp_path / "cache" / "benchmark.sqlite")).put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 90.0})
    runs = RunStore(str(tmp_path / "cache" / "runs"), today="2026-06-13")
    run = runs.create(session="s", query="why?", suffix="aaaa")
    run.state.update({"metric": "dau", "start": "2026-05-01", "end": "2026-05-03",
                      "genre": "survival", "platform": "roblox", "profile_name": "MyGame",
                      "ledger": []})
    runs.save(run)
    return run.run_id


def test_run_id_and_args_from_env(tmp_path, monkeypatch):
    import gaa.lab as lab
    monkeypatch.setenv("GAA_RUN_ID", "2026-06-13-x-aaaa")
    monkeypatch.setenv("GAA_TOOL_ARGS", json.dumps({"dim": "region"}))
    assert lab.run_id() == "2026-06-13-x-aaaa"
    assert lab.args() == {"dim": "region"}


def test_args_empty_when_unset(tmp_path, monkeypatch):
    import gaa.lab as lab
    monkeypatch.delenv("GAA_TOOL_ARGS", raising=False)
    assert lab.args() == {}


def test_run_state_and_loaders_return_copies(tmp_path, monkeypatch):
    import gaa.lab as lab
    rid = _workspace(tmp_path, monkeypatch)

    state = lab.run_state(rid)
    assert state["metric"] == "dau" and state["profile_name"] == "MyGame"
    state["metric"] = "MUTATED"
    assert lab.run_state(rid)["metric"] == "dau"

    df = lab.load_metrics("MyGame")
    assert len(df) == 2
    df.loc[0, "value"] = -999
    assert lab.load_metrics("MyGame")["value"].tolist() == [1000.0, 400.0]

    bench = lab.load_benchmark("survival", "roblox", "2026-05-01", "2026-05-03")
    assert bench


def test_scratch_dir_created_under_run(tmp_path, monkeypatch):
    import gaa.lab as lab
    rid = _workspace(tmp_path, monkeypatch)
    d = lab.scratch_dir(rid)
    assert d.exists() and d.name == "scratch"
    assert rid in str(d)
