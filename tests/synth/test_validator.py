from gaa.synth.validator import validate_citations
from gaa.schema.hypothesis import AttributionHypothesis, Cause, Scenario, Causes
from gaa.schema.confidence import Confidence
from gaa.schema.ledger import EvidenceLedger


def _ledger():
    led = EvidenceLedger()
    led.add(module="m", claim="c", value="v", source="s",
            source_type="internal", strength="high")  # L1
    return led


def _hyp():
    return AttributionHypothesis(
        main_story="x",
        confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(
            internal=[Cause(claim="ok", evidence_ids=["L1"], likelihood="Likely",
                            evidence_quality="Moderate"),
                      Cause(claim="bogus", evidence_ids=["L9"], likelihood="Likely",
                            evidence_quality="Weak")],
            market=[]),
        scenarios=[Scenario(description="grounded", likelihood="Possible",
                            evidence_quality="Weak", signals_to_watch=[])],
        evidence=[], assumptions_and_gaps=[])


def test_drops_uncited_causes_and_notes_gap():
    led = _ledger()
    h = validate_citations(_hyp(), led)
    claims = [c.claim for c in h.causes.internal]
    assert "ok" in claims and "bogus" not in claims  # L9 doesn't exist -> dropped
    assert any("dropped" in g.lower() or "uncited" in g.lower()
               for g in h.assumptions_and_gaps)
