from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Run(BaseModel):
    """A single analysis, persisted as a run directory on disk.

    Field-compatible with the old ``Job`` so ``AnalysisPipeline`` accepts it
    unchanged. ``state`` holds intermediate stage results (including the
    serialized ledger under ``state['ledger']``); ``activity`` is the append-only
    thinking trace; ``result`` is populated at the render stage.
    """

    run_id: str
    session: str
    query: str

    stage: str = "plan"
    status: Literal["running", "done", "error"] = "running"

    state: dict = Field(default_factory=dict)
    activity: list[dict] = Field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    def add_activity(self, stage: str, text: str) -> None:
        """Append an activity entry stamped with the current time.

        When ``$GAA_PROGRESS`` is set (in the container, the analyze pipeline runs
        inside the MCP subprocess), each entry is also appended as a JSONL line to
        that sidecar so the front door can tail it and narrate live GAA activity
        during the dead-air of a tool turn. Best-effort: never break a run.
        """
        entry = {"ts": _now_iso(), "stage": stage, "text": text}
        self.activity.append(entry)
        _emit_progress(entry)


def _emit_progress(entry: dict) -> None:
    path = os.environ.get("GAA_PROGRESS")
    if not path:
        return
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # progress narration is cosmetic — never break the run
        pass
