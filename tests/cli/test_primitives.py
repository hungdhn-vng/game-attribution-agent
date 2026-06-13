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


def _onboard_and_plan(tmp_path):
    """Onboard a 2-region game and create a run that has completed its plan stage."""
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({
        "day": ["2026-05-01", "2026-05-01", "2026-05-03", "2026-05-03"],
        "region": ["SEA", "NA", "SEA", "NA"],
        "dau": [1000, 800, 400, 770],
    }).to_csv(csv, index=False)
    _run(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
          "--name", "SurvivalGame", "--platform", "roblox", "--genre", "survival"],
         FakeLLM(_MAPPING), tmp_path)
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 97.0})
    started = _run(["analyze", "why did dau drop?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)
    return started["run_id"]


def test_segments_appends_region_entries(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["segments", "--run", rid, "--dimension", "region"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "segment"
    assert resp["new_entries"], "expected new ledger entries"
    assert all("region=" in e["claim"] or "no segment" in e["claim"] for e in resp["new_entries"])
    assert resp["ledger_count"] >= len(resp["new_entries"])


def test_segments_unknown_run_is_error(tmp_path):
    _env(tmp_path)
    resp = _run(["segments", "--run", "nope"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "error"
    assert "unknown run" in resp["error"].lower()


def test_detect_appends_anomaly_entry(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["detect", "--run", rid, "--metric", "dau"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "anomaly"
    assert any("dau" in e["claim"] for e in resp["new_entries"])


def test_market_appends_entry(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["market", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "market"
    assert resp["new_entries"]  # either a counterfactual verdict or a graceful "no benchmark" gap


def test_signals_appends_entry(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    resp = _run(["signals", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["module"] == "competitor"
    assert resp["new_entries"]  # with no configured signals source, a "no signals" gap entry


def test_synth_produces_hypothesis_from_ledger(tmp_path):
    rid = _onboard_and_plan(tmp_path)
    _run(["segments", "--run", rid, "--dimension", "region"], FakeLLM(_SYNTH), tmp_path)
    resp = _run(["synth", "--run", rid, "is it the SEA region?"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["main_story"] == "DAU dropped — internal."
    assert resp["confidence"]["likelihood"] in ("Very likely", "Likely", "Possible", "Unlikely")


def test_synth_unknown_run_is_error(tmp_path):
    _env(tmp_path)
    resp = _run(["synth", "--run", "nope", "q"], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "error"


def test_report_writes_dossier_files(tmp_path):
    import os as _os
    rid = _onboard_and_plan(tmp_path)
    _run(["segments", "--run", rid, "--dimension", "region"], FakeLLM(_SYNTH), tmp_path)
    _run(["synth", "--run", rid, "why?"], FakeLLM(_SYNTH), tmp_path)
    resp = _run(["report", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success"
    assert resp["report_path"].endswith("report.html")
    assert _os.path.exists(resp["report_path"])
    assert _os.path.exists(resp["summary_path"])
    html = open(resp["report_path"]).read().lower()
    assert "<html" in html


def test_report_without_hypothesis_is_error(tmp_path):
    rid = _onboard_and_plan(tmp_path)  # plan only, no synth
    resp = _run(["report", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "error"
    assert "synth" in resp["error"].lower()
