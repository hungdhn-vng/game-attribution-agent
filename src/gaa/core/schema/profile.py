from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


class ColumnMapping(BaseModel):
    date_col: str
    metric_cols: dict[str, str]  # source_col -> canonical metric name (e.g. "dau")
    dim_cols: dict[str, str] = {}  # source_col -> canonical dim name

    @field_validator("metric_cols")
    @classmethod
    def _non_empty_metric_names(cls, v: dict[str, str]) -> dict[str, str]:
        for src, canon in v.items():
            if not canon:
                raise ValueError(f"empty canonical metric name for column '{src}'")
        return v


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GameProfile(BaseModel):
    name: str
    platform: str
    genre: str
    mapping: ColumnMapping
    external_source_config: dict = {}
    created_at: str = Field(default_factory=_now_iso)
