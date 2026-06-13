from __future__ import annotations

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
        """Append an activity entry stamped with the current time."""
        self.activity.append({"ts": _now_iso(), "stage": stage, "text": text})
