from __future__ import annotations

import sqlite3
import uuid
from typing import Optional

from gaa.jobs.models import Job, _now_iso


class JobStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "  job_id     TEXT PRIMARY KEY,"
                "  session    TEXT,"
                "  status     TEXT,"
                "  json       TEXT NOT NULL,"
                "  updated_at TEXT"
                ")"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, session: str, query: str) -> Job:
        """Create and persist a new Job, returning it."""
        job = Job(job_id=uuid.uuid4().hex, session=session, query=query)
        self._upsert(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._conn() as c:
            row = c.execute(
                "SELECT json FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def save(self, job: Job) -> None:
        """Refresh updated_at and upsert the job."""
        job.updated_at = _now_iso()
        self._upsert(job)

    def active_for_session(self, session: str) -> Optional[Job]:
        """Return the most recent running job for a session, or None."""
        with self._conn() as c:
            row = c.execute(
                "SELECT json FROM jobs "
                "WHERE session=? AND status='running' "
                "ORDER BY updated_at DESC LIMIT 1",
                (session,),
            ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def cleanup(self, older_than_iso: str) -> int:
        """Delete jobs with updated_at < older_than_iso; return count deleted."""
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM jobs WHERE updated_at < ?", (older_than_iso,)
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert(self, job: Job) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs(job_id, session, status, json, updated_at) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET "
                "  session=excluded.session,"
                "  status=excluded.status,"
                "  json=excluded.json,"
                "  updated_at=excluded.updated_at",
                (job.job_id, job.session, job.status, job.model_dump_json(), job.updated_at),
            )
