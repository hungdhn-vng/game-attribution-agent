from gaa.runs.models import Run


def test_run_defaults():
    run = Run(run_id="2026-06-13-revenue-drop-k3f9", session="s1", query="why did revenue drop?")
    assert run.stage == "plan"
    assert run.status == "running"
    assert run.state == {}
    assert run.activity == []
    assert run.result is None
    assert run.error is None
    assert run.created_at and run.updated_at


def test_add_activity_appends_entry():
    run = Run(run_id="r1", session="s1", query="q")
    run.add_activity("plan", "scanned metrics")
    assert len(run.activity) == 1
    entry = run.activity[0]
    assert entry["stage"] == "plan"
    assert entry["text"] == "scanned metrics"
    assert "ts" in entry


def test_run_round_trips_through_json():
    run = Run(run_id="r1", session="s1", query="q")
    run.state["metric"] = "revenue"
    run.add_activity("plan", "x")
    restored = Run.model_validate_json(run.model_dump_json())
    assert restored.state["metric"] == "revenue"
    assert restored.activity[0]["text"] == "x"
