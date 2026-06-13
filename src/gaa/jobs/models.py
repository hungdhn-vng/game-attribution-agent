from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job(BaseModel):
    job_id: str
    session: str
    query: str

    stage: str = "plan"
    status: Literal["running", "done", "error"] = "running"

    state: dict = Field(default_factory=dict)
    activity: list[dict] = Field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    updated_at: str = Field(default_factory=_now_iso)

    def add_activity(self, stage: str, text: str) -> None:
        """Append an activity entry with the current timestamp."""
        self.activity.append({"ts": _now_iso(), "stage": stage, "text": text})
