import io
import json
import os
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.profile_store import ProfileStore


_PRESET = {
    "main_story": "DAU dropped — internal issues.",
    "rationale": "SEA drove most of the decline.",
    "causes": {"internal": [{"claim": "SEA collapsed", "evidence_ids": ["L1"], "likelihood": "Likely"}],
               "market": [{"claim": "Genre flat", "evidence_ids": ["L1"], "likelihood": "Possible"}]},
    "scenarios": [], "risks": [], "assumptions_and_gaps": [],
}


def _seed_workspace(tmp_path):
    """Populate the same paths build_context will read from."""
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")

    profiles = ProfileStore(os.environ["GAA_DB_PATH"])
    profiles.save(GameProfile(
        name="SurvivalGame", platform="roblox", genre="survival",
        mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}),
    ))
    profiles.set_active("SurvivalGame")

    rows = []
    for d, sea, na in [("2026-05-01", 1000.0, 800.0), ("2026-05-03", 400.0, 770.0)]:
        rows.append({"date": d, "metric": "dau", "value": sea, "region": "SEA"})
        rows.append({"date": d, "metric": "dau", "value": na, "region": "NA"})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["platform", "version", "cohort", "device", "source"]:
        df[col] = None
    MetricsStore(os.environ["GAA_CACHE_DIR"] + "/metrics").save("SurvivalGame", df)

    bstore = BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite")
    bstore.put_quant("roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})


def _run(argv, llm):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_analyze_then_status_reaches_done(tmp_path):
    _seed_workspace(tmp_path)
    llm = FakeLLM(_PRESET)

    started = _run(["analyze", "why did dau drop?", "--budget", "0"], llm)
    assert started["run_id"].startswith("2026-06-13-")
    assert started["status"] in ("running", "done")

    run_id = started["run_id"]
    # Drive to completion with repeated steps (budget 0 → one stage per call).
    seen_done = started["done"]
    for _ in range(10):
        if seen_done:
            break
        resp = _run(["step", run_id], llm)
        seen_done = resp["done"]
    assert seen_done, "run did not reach done within 10 steps"

    final = _run(["status", run_id], llm)
    assert final["status"] == "done"
    assert final["report_path"].endswith("report.html")
    assert os.path.exists(final["report_path"])


def test_status_does_not_advance(tmp_path):
    _seed_workspace(tmp_path)
    llm = FakeLLM(_PRESET)
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], llm)
    rid = started["run_id"]
    stage_before = _run(["status", rid], llm)["stage"]
    stage_after = _run(["status", rid], llm)["stage"]
    assert stage_before == stage_after  # pure read never moves the stage


def test_jobs_lists_created_run(tmp_path):
    _seed_workspace(tmp_path)
    llm = FakeLLM(_PRESET)
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], llm)
    listing = _run(["jobs"], llm)
    ids = [r["run_id"] for r in listing["runs"]]
    assert started["run_id"] in ids


def test_status_unknown_run_is_error(tmp_path):
    _seed_workspace(tmp_path)
    resp = _run(["status", "does-not-exist"], FakeLLM(_PRESET))
    assert resp["status"] == "error"
    assert "unknown run" in resp["error"].lower()
