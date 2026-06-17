from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import pandas as pd

from gaa.core.schema.ingest_plan import ReadSpec


@dataclass
class RawTable:
    """A raw, not-yet-canonicalized table plus how to re-read it."""
    df: pd.DataFrame
    read_spec: ReadSpec
    notes: list[str] = field(default_factory=list)


class Reader(Protocol):
    def read(self, data: bytes, spec: Optional[ReadSpec] = None) -> RawTable: ...
