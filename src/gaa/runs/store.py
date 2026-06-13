from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

from gaa.runs.models import Run, _now_iso
from gaa.runs.slug import make_run_id


class RunBusy(Exception):
    """Raised when a run directory is locked by another advance in progress."""


class RunStore:
    """Filesystem-backed store of analysis runs.

    Layout: ``<root>/<run_id>/{job.json, activity.log, ledger.jsonl,
    summary.md, report.html, .lock}``.
    """

    def __init__(self, root: str, today: Optional[str] = None) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._today = today or date.today().isoformat()

    # ---- paths ----
    def _dir(self, run_id: str) -> Path:
        return self._root / run_id

    def path_for(self, run_id: str) -> Path:
        """Public accessor for a run's directory (consumers: CLI, future proxy)."""
        return self._dir(run_id)

    # ---- create / read / write ----
    def create(self, session: str, query: str, suffix: Optional[str] = None) -> Run:
        run_id = make_run_id(query, today=self._today, suffix=suffix)
        run = Run(run_id=run_id, session=session, query=query)
        self._dir(run_id).mkdir(parents=True, exist_ok=True)
        self.save(run)
        return run

    def get(self, run_id: str) -> Optional[Run]:
        path = self._dir(run_id) / "job.json"
        if not path.exists():
            return None
        return Run.model_validate_json(path.read_text())

    def save(self, run: Run) -> None:
        run.updated_at = _now_iso()
        d = self._dir(run.run_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "job.json.tmp"
        tmp.write_text(run.model_dump_json())
        os.replace(tmp, d / "job.json")
        self._write_projections(d, run)

    def _write_projections(self, d: Path, run: Run) -> None:
        lines = [f'{a["ts"]} | {a["stage"]} | {a["text"]}' for a in run.activity]
        (d / "activity.log").write_text("\n".join(lines) + ("\n" if lines else ""))

        ledger = run.state.get("ledger", [])
        with (d / "ledger.jsonl").open("w") as f:
            for entry in ledger:
                f.write(json.dumps(entry) + "\n")

        if run.status == "done" and run.result:
            (d / "summary.md").write_text(run.result.get("markdown_summary", ""))
            (d / "report.html").write_text(run.result.get("html", ""))

    # ---- listing / cleanup ----
    def list(self, session: Optional[str] = None) -> list[dict]:
        out: list[dict] = []
        for child in self._root.iterdir():
            if not child.is_dir():
                continue
            jp = child / "job.json"
            if not jp.exists():
                continue
            run = Run.model_validate_json(jp.read_text())
            if session is not None and run.session != session:
                continue
            out.append({
                "run_id": run.run_id,
                "session": run.session,
                "query": run.query,
                "stage": run.stage,
                "status": run.status,
                "updated_at": run.updated_at,
            })
        out.sort(key=lambda r: r["updated_at"], reverse=True)
        return out

    def prune(self, older_than_iso: str) -> int:
        """Delete runs whose updated_at < older_than_iso; return count removed."""
        import shutil
        removed = 0
        for child in self._root.iterdir():
            jp = child / "job.json"
            if not (child.is_dir() and jp.exists()):
                continue
            run = Run.model_validate_json(jp.read_text())
            if run.updated_at < older_than_iso:
                shutil.rmtree(child)
                removed += 1
        return removed

    # ---- locking ----
    @contextmanager
    def locked(self, run_id: str) -> Iterator[None]:
        """Exclusive non-blocking lock on a run directory.

        Raises :class:`RunBusy` if another process holds the lock, so a
        concurrent caller can fall back to a read-only status instead of
        double-advancing the pipeline.
        """
        d = self._dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        f = (d / ".lock").open("w")
        try:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RunBusy(run_id) from exc
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            finally:
                f.close()
