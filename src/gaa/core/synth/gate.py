from collections import Counter
from gaa.core.schema.hypothesis import AttributionHypothesis

_DOWNGRADE = {"Strong": "Moderate", "Moderate": "Weak", "Weak": "Weak"}


def _primary_direction(h: AttributionHypothesis) -> str:
    if h.causes.internal:
        return "internal"
    if h.causes.market:
        return "market"
    return "none"


def consistency_score(samples: list) -> float:
    dirs = [_primary_direction(h) for h in samples]
    if not dirs:
        return 1.0
    return Counter(dirs).most_common(1)[0][1] / len(dirs)


def apply_gate(hypothesis: AttributionHypothesis, samples: list,
               threshold: float = 0.67) -> AttributionHypothesis:
    score = consistency_score(samples)
    if score < threshold:
        hypothesis.confidence.evidence_quality = _DOWNGRADE[hypothesis.confidence.evidence_quality]
        hypothesis.assumptions_and_gaps.append(
            f"Model self-consistency low ({score:.0%} agreement across {len(samples)} samples) "
            f"→ headline evidence quality downgraded one notch.")
    return hypothesis
