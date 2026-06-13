import os

from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM


_PRESET = {
    "main_story": "DAU dropped — internal.",
    "rationale": "SEA drove it.",
    "causes": {"internal": [{"claim": "SEA fell", "evidence_ids": ["L1"], "likelihood": "Likely"}],
               "market": []},
    "scenarios": [], "risks": [], "assumptions_and_gaps": [],
}


def test_build_context_wires_pipeline_and_store(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    ctx = build_context(llm=FakeLLM(_PRESET), today="2026-06-13")
    assert ctx.pipeline is not None
    assert ctx.runs is not None
    assert ctx.profiles is not None
    # run store root lives under the cache dir
    assert "runs" in str(ctx.runs._root)
