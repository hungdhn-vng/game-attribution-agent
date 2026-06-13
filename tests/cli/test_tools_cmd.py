import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    os.environ["GAA_TOOLS_DIR"] = str(tmp_path / "cache" / "tools")


def _run(argv, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def _script(tmp_path, body="print('hi')\n"):
    p = tmp_path / "scratch.py"
    p.write_text(body)
    return str(p)


def test_tools_promote(tmp_path):
    resp = _run(["tools", "promote", "--name", "t", "--description", "d",
                 "--script", _script(tmp_path)], tmp_path)
    assert resp["status"] == "success"
    assert resp["tool"] == "t" and resp["md5"]


def test_tools_promote_missing_script_is_error(tmp_path):
    resp = _run(["tools", "promote", "--name", "t", "--description", "d",
                 "--script", str(tmp_path / "nope.py")], tmp_path)
    assert resp["status"] == "error"


import pandas as pd
from gaa.core.llm.client import FakeLLM
from gaa.core.store.benchmark_store import BenchmarkStore

_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_SYNTH = {"main_story": "x", "rationale": "y",
          "causes": {"internal": [{"claim": "c", "evidence_ids": ["L1"], "likelihood": "Likely"}], "market": []},
          "scenarios": [], "risks": [], "assumptions_and_gaps": []}


def _run_llm(argv, llm, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, llm=llm, today="2026-06-13")
    return json.loads(buf.getvalue())


def _planned_run(tmp_path):
    csv = tmp_path / "m.csv"
    pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                  "dau": [1000, 400]}).to_csv(csv, index=False)
    _run_llm(["onboard", "confirm", "--csv", str(csv), "--mapping", json.dumps(_MAPPING),
              "--name", "G", "--platform", "roblox", "--genre", "survival"], FakeLLM(_MAPPING), tmp_path)
    BenchmarkStore(os.environ["GAA_CACHE_DIR"] + "/benchmark.sqlite").put_quant(
        "roblox", "survival", raw={"2026-05-01": 100.0, "2026-05-03": 90.0})
    return _run_llm(["analyze", "why?", "--budget", "0"], FakeLLM(_SYNTH), tmp_path)["run_id"]


_TOOL_BODY = (
    "from gaa import lab\n"
    "rid = lab.run_id()\n"
    "st = lab.run_state(rid)\n"
    "df = lab.load_metrics(st['profile_name'])\n"
    "lab.add_evidence(rid, claim='adhoc finding', value=str(len(df)), source='tool')\n"
    "print('ok')\n"
)


def test_tools_run_executes_and_adds_tool_evidence(tmp_path):
    from gaa.runs.store import RunStore
    rid = _planned_run(tmp_path)
    script = tmp_path / "tool_body.py"
    script.write_text(_TOOL_BODY)
    assert _run(["tools", "promote", "--name", "counter", "--description", "row counter",
                 "--script", str(script)], tmp_path)["status"] == "success"

    resp = _run(["tools", "run", "counter", "--run", rid], tmp_path)
    assert resp["status"] == "success", resp
    assert resp["returncode"] == 0

    run = RunStore(os.environ["GAA_CACHE_DIR"] + "/runs").get(rid)
    tool_entries = [e for e in run.state["ledger"] if e["module"] == "tool:counter"]
    assert tool_entries, "expected a tool:counter ledger entry"
    assert tool_entries[-1]["strength"] == "med"


def test_tools_run_refuses_tampered_tool(tmp_path):
    rid = _planned_run(tmp_path)
    script = tmp_path / "tool_body.py"
    script.write_text(_TOOL_BODY)
    _run(["tools", "promote", "--name", "counter", "--description", "d", "--script", str(script)], tmp_path)
    (tmp_path / "cache" / "tools" / "counter" / "tool.py").write_text("print('evil')\n")
    resp = _run(["tools", "run", "counter", "--run", rid], tmp_path)
    assert resp["status"] == "error"
    assert "md5" in resp["error"].lower()
