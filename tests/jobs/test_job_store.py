"""Tests for JobStore — written first (TDD), implementation follows."""

import pytest
from gaa.jobs.job_store import JobStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_store(tmp_path) -> JobStore:
    return JobStore(str(tmp_path / "jobs.db"))


# ---------------------------------------------------------------------------
# create / get
# ---------------------------------------------------------------------------


def test_create_returns_job_with_expected_defaults(tmp_path):
    store = make_store(tmp_path)
    job = store.create(session="sess-1", query="what is DAU?")

    assert job.job_id, "job_id must be non-empty"
    assert job.session == "sess-1"
    assert job.query == "what is DAU?"
    assert job.status == "running"
    assert job.stage == "plan"
    assert job.state == {}
    assert job.activity == []
    assert job.result is None
    assert job.error is None


def test_get_round_trips_job(tmp_path):
    store = make_store(tmp_path)
    created = store.create(session="sess-1", query="round-trip")

    fetched = store.get(created.job_id)

    assert fetched is not None
    assert fetched.job_id == created.job_id
    assert fetched.session == created.session
    assert fetched.query == created.query
    assert fetched.status == created.status


def test_get_missing_id_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.get("nonexistent-id") is None


# ---------------------------------------------------------------------------
# save — persists mutations
# ---------------------------------------------------------------------------


def test_save_persists_mutations(tmp_path):
    store = make_store(tmp_path)
    job = store.create(session="sess-2", query="save test")

    job.stage = "search"
    job.state = {"urls": ["https://example.com"]}
    job.status = "done"
    job.result = {"answer": "42"}

    store.save(job)

    reloaded = store.get(job.job_id)
    assert reloaded is not None
    assert reloaded.stage == "search"
    assert reloaded.state == {"urls": ["https://example.com"]}
    assert reloaded.status == "done"
    assert reloaded.result == {"answer": "42"}


# ---------------------------------------------------------------------------
# add_activity
# ---------------------------------------------------------------------------


def test_add_activity_appends_entry(tmp_path):
    store = make_store(tmp_path)
    job = store.create(session="sess-3", query="activity test")

    job.add_activity(stage="plan", text="Starting plan")
    job.add_activity(stage="search", text="Searching web")

    assert len(job.activity) == 2
    assert job.activity[0]["stage"] == "plan"
    assert job.activity[0]["text"] == "Starting plan"
    assert "ts" in job.activity[0]
    assert job.activity[1]["stage"] == "search"


def test_add_activity_persists_through_save_get(tmp_path):
    store = make_store(tmp_path)
    job = store.create(session="sess-4", query="activity persist test")

    job.add_activity(stage="plan", text="Planning")
    store.save(job)

    reloaded = store.get(job.job_id)
    assert reloaded is not None
    assert len(reloaded.activity) == 1
    assert reloaded.activity[0]["text"] == "Planning"


# ---------------------------------------------------------------------------
# active_for_session
# ---------------------------------------------------------------------------


def test_active_for_session_returns_running_job(tmp_path):
    store = make_store(tmp_path)
    job = store.create(session="sess-5", query="active test")

    active = store.active_for_session("sess-5")
    assert active is not None
    assert active.job_id == job.job_id


def test_active_for_session_returns_none_after_done(tmp_path):
    store = make_store(tmp_path)
    job = store.create(session="sess-6", query="done test")

    job.status = "done"
    store.save(job)

    active = store.active_for_session("sess-6")
    assert active is None


def test_active_for_session_returns_none_for_unknown_session(tmp_path):
    store = make_store(tmp_path)
    assert store.active_for_session("unknown-session") is None


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def test_cleanup_deletes_old_rows(tmp_path):
    store = make_store(tmp_path)
    store.create(session="s1", query="q1")
    store.create(session="s2", query="q2")

    # Use a far-future ISO timestamp so all rows qualify as "old"
    future_iso = "9999-12-31T23:59:59+00:00"
    count = store.cleanup(older_than_iso=future_iso)

    assert count == 2

    # Store is now empty
    assert store.active_for_session("s1") is None
    assert store.active_for_session("s2") is None


def test_cleanup_returns_zero_when_nothing_to_delete(tmp_path):
    store = make_store(tmp_path)
    store.create(session="s1", query="q1")

    # Use a past ISO timestamp so no rows qualify
    past_iso = "2000-01-01T00:00:00+00:00"
    count = store.cleanup(older_than_iso=past_iso)

    assert count == 0
