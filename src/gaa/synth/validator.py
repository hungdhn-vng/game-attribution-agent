from gaa.schema.hypothesis import AttributionHypothesis, Cause
from gaa.schema.ledger import EvidenceLedger


def _valid(cause: Cause, valid_ids: set) -> bool:
    return any(i in valid_ids for i in cause.evidence_ids)


def validate_citations(h: AttributionHypothesis, ledger: EvidenceLedger) -> AttributionHypothesis:
    valid_ids = {e.id for e in ledger.all()}
    dropped = 0

    kept_internal = [c for c in h.causes.internal if _valid(c, valid_ids)]
    kept_market = [c for c in h.causes.market if _valid(c, valid_ids)]
    dropped += (len(h.causes.internal) - len(kept_internal))
    dropped += (len(h.causes.market) - len(kept_market))
    h.causes.internal = kept_internal
    h.causes.market = kept_market

    # prune dangling evidence_ids that don't exist
    for c in h.causes.internal + h.causes.market:
        c.evidence_ids = [i for i in c.evidence_ids if i in valid_ids]

    if dropped:
        h.assumptions_and_gaps.append(
            f"{dropped} uncited claim(s) dropped for lacking ledger evidence.")
    return h
