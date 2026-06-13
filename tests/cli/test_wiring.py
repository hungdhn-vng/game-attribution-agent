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


def test_build_context_without_llm_key_does_not_raise(tmp_path, monkeypatch):
    # No LLM credentials in the environment at all.
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    # llm=None → real (but lazy) construction path. Must NOT raise.
    ctx = build_context(today="2026-06-13")
    assert ctx.pipeline is not None
    assert ctx.profiles is not None


def test_jobs_and_unknown_status_work_without_llm_key(tmp_path, monkeypatch):
    import io, json
    from contextlib import redirect_stdout
    from gaa.cli.main import main

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["jobs"], today="2026-06-13")  # no llm injected → lazy real path
    resp = json.loads(buf.getvalue())
    assert resp["status"] == "success"   # NOT a credentials error
    assert resp["runs"] == []

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["status", "nope"], today="2026-06-13")
    resp = json.loads(buf.getvalue())
    assert resp["status"] == "error"
    assert "unknown run" in resp["error"].lower()   # NOT a credentials error
