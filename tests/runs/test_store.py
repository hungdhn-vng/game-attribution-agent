import json

import pytest

from gaa.runs.models import Run
from gaa.runs.store import RunStore, RunBusy


def test_create_makes_directory_and_job_json(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="why did revenue drop?", suffix="aaaa")
    assert run.run_id == "2026-06-13-revenue-drop-aaaa"
    assert (tmp_path / run.run_id / "job.json").exists()


def test_get_round_trips(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="bbbb")
    run.state["metric"] = "revenue"
    store.save(run)
    loaded = store.get(run.run_id)
    assert loaded is not None
    assert loaded.state["metric"] == "revenue"


def test_get_unknown_returns_none(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    assert store.get("nope") is None


def test_save_projects_activity_and_ledger(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="cccc")
    run.add_activity("plan", "scanned metrics")
    run.state["ledger"] = [
        {"id": "L1", "module": "anomaly", "claim": "DAU fell", "value": "-30%",
         "source": "internal", "source_type": "internal", "strength": "high"}
    ]
    store.save(run)

    activity = (tmp_path / run.run_id / "activity.log").read_text()
    assert "plan" in activity and "scanned metrics" in activity

    ledger_lines = (tmp_path / run.run_id / "ledger.jsonl").read_text().strip().splitlines()
    assert len(ledger_lines) == 1
    assert json.loads(ledger_lines[0])["id"] == "L1"


def test_save_writes_report_files_when_done(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="dddd")
    run.status = "done"
    run.result = {"markdown_summary": "# Summary", "html": "<html>x</html>"}
    store.save(run)
    assert (tmp_path / run.run_id / "summary.md").read_text() == "# Summary"
    assert (tmp_path / run.run_id / "report.html").read_text() == "<html>x</html>"


def test_list_returns_runs_newest_first(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    a = store.create(session="s1", query="alpha", suffix="0001")
    b = store.create(session="s2", query="beta", suffix="0002")
    b.add_activity("plan", "touch")  # bump updated_at on save
    store.save(b)
    listed = store.list()
    ids = [r["run_id"] for r in listed]
    assert set(ids) == {a.run_id, b.run_id}
    assert ids[0] == b.run_id  # most recently updated first


def test_list_filters_by_session(tmp_path):
    store = RunStore(str(tmp_path), today="2026-06-13")
    store.create(session="s1", query="alpha", suffix="0001")
    store.create(session="s2", query="beta", suffix="0002")
    s1 = store.list(session="s1")
    assert len(s1) == 1 and s1[0]["session"] == "s1"


def test_locked_raises_runbusy_when_already_held(tmp_path):
    import fcntl
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s1", query="q", suffix="eeee")
    lock_path = tmp_path / run.run_id / ".lock"
    held = lock_path.open("w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RunBusy):
            with store.locked(run.run_id):
                pass
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()


def test_concurrent_reads_during_writes_never_corrupt(tmp_path):
    import threading
    store = RunStore(str(tmp_path), today="2026-06-13")
    run = store.create(session="s", query="q", suffix="zzzz")
    # Large ledger so the JSON is big enough to expose a truncate-write window.
    run.state["ledger"] = [
        {"id": f"L{i}", "module": "m", "claim": "c" * 200, "value": "v",
         "source": "s", "source_type": "internal", "strength": "high"}
        for i in range(200)
    ]
    errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                r = store.get(run.run_id)
                if r is not None:
                    _ = r.run_id
            except Exception as e:  # corrupt/partial read
                errors.append(repr(e))

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(300):
            run.state["n"] = i
            store.save(run)
    finally:
        stop.set()
        t.join()

    assert not errors, f"reader observed corrupt job.json under concurrent writes: {errors[:3]}"
