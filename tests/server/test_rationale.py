from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.cli.main import _run_view
from gaa.runs.models import Run


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_run_view_surfaces_rationale_when_present(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    run = Run(run_id="r1", session="s", query="why?")
    run.status = "done"
    run.state["hypothesis"] = {"main_story": "x", "rationale": "SEA drove the drop."}
    assert _run_view(ctx, run)["rationale"] == "SEA drove the drop."


def test_run_view_omits_rationale_when_absent(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    run = Run(run_id="r2", session="s", query="why?")
    run.status = "running"
    assert "rationale" not in _run_view(ctx, run)
