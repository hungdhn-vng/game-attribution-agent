from gaa.core.schema.ledger import LedgerEntry
from gaa.core.schema.confidence import EvidenceQuality


def evidence_quality(entries: list[LedgerEntry]) -> EvidenceQuality:
    """Rule-based analytical confidence from supporting ledger entries.

    Score = #entries
          + 2 if internal AND external both corroborate
          + 1 if any entry has high strength
    Strong >= 4, Moderate >= 2, else Weak.
    """
    if not entries:
        return "Weak"
    n = len(entries)
    types = {e.source_type for e in entries}
    has_both = "internal" in types and "external" in types
    has_high = any(e.strength == "high" for e in entries)
    score = n + (2 if has_both else 0) + (1 if has_high else 0)
    if score >= 4:
        return "Strong"
    if score >= 2:
        return "Moderate"
    return "Weak"
