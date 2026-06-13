import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.benchmark_store import BenchmarkStore


_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {
    "main_story": "DAU dropped — internal.",
    "rationale": "SEA drove it.",
    "causes": {"internal": [{"claim": "SEA fell", "evidence_ids": ["L1"], "likelihood": "Likely"}],
               "market": []},
    "scenarios": [], "risks": [], "assumptions_and_gaps": [],
}


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")


def _run(argv, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=FakeLLM(_SYNTH), today="2026-06-13")
    return json.loads(buf.getvalue())


def test_drilldown_then_resynth_then_report(tmp_path):
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
              "--name", "SurvivalGame", "--platform", "roblox", "--genre", "survival"],
             llm=FakeLLM(_MAPPING), today="2026-06-13")
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})

    started = _run(["analyze", "why did dau drop?"], tmp_path)
    rid = started["run_id"]
    done = started["done"]
    for _ in range(10):
        if done:
            break
        done = _run(["step", rid], tmp_path)["done"]
    assert done

    count_before = _run(["status", rid], tmp_path)["ledger_count"]

    seg = _run(["segments", "--run", rid, "--dimension", "region"], tmp_path)
    assert seg["status"] == "success" and seg["new_entries"]
    count_after = _run(["status", rid], tmp_path)["ledger_count"]
    assert count_after > count_before

    assert _run(["synth", "--run", rid, "was it SEA?"], tmp_path)["status"] == "success"
    rep = _run(["report", "--run", rid], tmp_path)
    assert rep["status"] == "success"
    assert os.path.exists(rep["report_path"])
