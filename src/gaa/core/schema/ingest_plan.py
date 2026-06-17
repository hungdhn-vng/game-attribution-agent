from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, model_validator


class ReadSpec(BaseModel):
    """How a RawTable was (and must be re-)read. Recorded at propose time so the
    confirm step re-reads the source identically."""
    format: Literal["csv", "excel", "json", "jsonl", "paste"]
    delimiter: Optional[str] = None
    encoding: Optional[str] = None
    sheet: Optional[str] = None
    header_row: int = 0


class IngestionPlan(BaseModel):
    """Declarative recipe (LLM-authored) for turning a RawTable into the canonical
    long frame. Never code."""
    read_spec: ReadSpec
    orientation: Literal["wide", "long"]
    date_col: str
    # WIDE: each metric is its own column →  source_col -> final metric name
    metric_cols: dict[str, str] = {}
    # LONG: one column holds metric names, another holds values
    long_metric_col: Optional[str] = None
    long_value_col: Optional[str] = None
    dim_cols: dict[str, str] = {}       # source_col -> dim name (canonical OR preserved)
    confidence: float = 0.0             # 0.0–1.0 overall
    notes: list[str] = []               # plain-language decisions/uncertainties

    @model_validator(mode="after")
    def _check_orientation_fields(self) -> "IngestionPlan":
        if self.orientation == "wide" and not self.metric_cols:
            raise ValueError("wide plan requires non-empty metric_cols")
        if self.orientation == "long" and not (self.long_metric_col and self.long_value_col):
            raise ValueError("long plan requires long_metric_col and long_value_col")
        return self
