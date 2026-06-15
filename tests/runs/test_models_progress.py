import json

from gaa.runs.models import Run


def test_add_activity_appends_progress_jsonl_when_env_set(tmp_path, monkeypatch):
    p = tmp_path / "progress.jsonl"
    monkeypatch.setenv("GAA_PROGRESS", str(p))
    run = Run(run_id="r1", session="s1", query="q")
    run.add_activity("plan", "Scanned metrics")
    run.add_activity("synth", "Sampled 3x")

    lines = p.read_text().splitlines()
    assert len(lines) == 2
    last = json.loads(lines[1])
    assert last["stage"] == "synth"
    assert last["text"] == "Sampled 3x"
    assert "ts" in last
    # the in-memory trace is unaffected
    assert [a["text"] for a in run.activity] == ["Scanned metrics", "Sampled 3x"]


def test_add_activity_no_progress_file_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("GAA_PROGRESS", raising=False)
    run = Run(run_id="r1", session="s1", query="q")
    run.add_activity("plan", "x")
    assert run.activity[0]["text"] == "x"  # still recorded in memory, no file written


def test_add_activity_progress_is_best_effort_on_bad_path(tmp_path, monkeypatch):
    # parent dir does not exist → write must be swallowed, never break a run
    monkeypatch.setenv("GAA_PROGRESS", str(tmp_path / "missing" / "progress.jsonl"))
    run = Run(run_id="r1", session="s1", query="q")
    run.add_activity("plan", "x")  # must not raise
    assert run.activity[0]["text"] == "x"
