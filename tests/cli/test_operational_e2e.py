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


def _run(argv, llm, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_full_operational_loop(tmp_path):
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)

    # 1. onboard
    r = _run(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
              "--name", "SurvivalGame", "--platform", "roblox", "--genre", "survival"],
             FakeLLM(_MAPPING), tmp_path)
    assert r["status"] == "success"

    # benchmark control series so the counterfactual has data
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})

    # 2. config
    assert _run(["config", "set", "benchmark_mode", "snapshot"], FakeLLM(_SYNTH), tmp_path)["status"] == "success"

    # 3. doctor (no key → warn-level only, still ok)
    assert _run(["doctor"], FakeLLM(_SYNTH), tmp_path)["ok"] is True

    # 4. analyze to done
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)
    rid = started["run_id"]
    done = started["done"]
    for _ in range(10):
        if done:
            break
        done = _run(["step", rid], FakeLLM(_SYNTH), tmp_path)["done"]
    assert done, "analysis did not reach done"
    final = _run(["status", rid], FakeLLM(_SYNTH), tmp_path)
    assert final["status"] == "done"
