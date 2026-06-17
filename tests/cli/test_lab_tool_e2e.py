import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

import pandas as pd

from gaa.cli.main import main
from gaa.core.llm.client import FakeLLM
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.runs.store import RunStore


_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_PLAN = {**_MAPPING, "orientation": "wide", "confidence": 0.95, "notes": [],
         "read_spec": {"format": "csv", "delimiter": ",", "encoding": "utf-8", "header_row": 0}}
_SYNTH = {"main_story": "x", "rationale": "y",
          "causes": {"internal": [{"claim": "c", "evidence_ids": ["L1"], "likelihood": "Likely"}], "market": []},
          "scenarios": [], "risks": [], "assumptions_and_gaps": []}

_SCRIPT = (
    "from gaa import lab\n"
    "rid = lab.run_id()\n"
    "st = lab.run_state(rid)\n"
    "df = lab.load_metrics(st['profile_name'])\n"
    "lab.add_evidence(rid, claim='rows=' + str(len(df)), value=str(len(df)), source='scratch')\n"
    "print('done', len(df))\n"
)


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    os.environ["GAA_TOOLS_DIR"] = str(tmp_path / "cache" / "tools")


def _run(argv, llm, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_scratch_to_promoted_tool_lifecycle(tmp_path):
    _env(tmp_path)
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    _run(["onboard", "confirm", "--csv", str(csv), "--plan", json.dumps(_PLAN),
          "--name", "G", "--platform", "roblox", "--genre", "survival"], FakeLLM(_MAPPING), tmp_path)
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 90.0})
    rid = _run(["analyze", "why?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)["run_id"]

    runs = RunStore(os.environ["GAA_CACHE_DIR"] + "/runs")

    import gaa.lab as lab
    scratch = lab.scratch_dir(rid) / "01-rows.py"
    scratch.write_text(_SCRIPT)
    proc = subprocess.run([sys.executable, str(scratch)],
                          env={**os.environ, "GAA_RUN_ID": rid},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    adhoc = [e for e in runs.get(rid).state["ledger"] if e["module"] == "adhoc"]
    assert adhoc, "scratch run should add an adhoc entry"

    assert _run(["tools", "promote", "--name", "rows", "--description", "count rows",
                 "--script", "01-rows.py", "--run", rid], FakeLLM(_SYNTH), tmp_path)["status"] == "success"

    resp = _run(["tools", "run", "rows", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert resp["status"] == "success" and resp["returncode"] == 0
    tool_entries = [e for e in runs.get(rid).state["ledger"] if e["module"] == "tool:rows"]
    assert tool_entries

    (tmp_path / "cache" / "tools" / "rows" / "tool.py").write_text("print('evil')\n")
    bad = _run(["tools", "run", "rows", "--run", rid], FakeLLM(_SYNTH), tmp_path)
    assert bad["status"] == "error" and "md5" in bad["error"].lower()
