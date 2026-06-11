from dataclasses import dataclass, field
from typing import Optional, Protocol
import pandas as pd
from gaa.schema.profile import GameProfile
from gaa.schema.ledger import EvidenceLedger


@dataclass
class AnalysisContext:
    profile: GameProfile
    metrics: pd.DataFrame            # canonical long-format
    query: str
    metric: Optional[str] = None     # e.g. "dau"; None triggers scan mode
    start: Optional[str] = None      # ISO date
    end: Optional[str] = None
    direction: Optional[str] = None  # "down" | "up"
    extras: dict = field(default_factory=dict)


class AnalysisModule(Protocol):
    name: str

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        """Append findings to the ledger. Never raise on missing data —
        record a derived 'data gap' entry instead."""
        ...
