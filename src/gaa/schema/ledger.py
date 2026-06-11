from typing import Literal, Optional
from pydantic import BaseModel

SourceType = Literal["internal", "external", "derived"]
Strength = Literal["high", "med", "low"]


class LedgerEntry(BaseModel):
    id: str
    module: str
    claim: str
    value: str
    source: str
    source_type: SourceType
    strength: Strength
    timeframe: Optional[str] = None


class EvidenceLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def add(self, *, module: str, claim: str, value: str, source: str,
            source_type: SourceType, strength: Strength,
            timeframe: Optional[str] = None) -> str:
        eid = f"L{len(self._entries) + 1}"
        self._entries.append(LedgerEntry(
            id=eid, module=module, claim=claim, value=value, source=source,
            source_type=source_type, strength=strength, timeframe=timeframe))
        return eid

    def get(self, eid: str) -> Optional[LedgerEntry]:
        return next((e for e in self._entries if e.id == eid), None)

    def by_ids(self, ids: list[str]) -> list[LedgerEntry]:
        idset = set(ids)
        return [e for e in self._entries if e.id in idset]

    def all(self) -> list[LedgerEntry]:
        return list(self._entries)
