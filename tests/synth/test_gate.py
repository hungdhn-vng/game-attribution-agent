from gaa.core.synth.gate import consistency_score, apply_gate
from gaa.core.schema.hypothesis import AttributionHypothesis, Cause, Causes
from gaa.core.schema.confidence import Confidence


def _h(primary, eq="Strong"):
    causes = Causes(internal=[Cause(claim="i", evidence_ids=["L1"], likelihood="Likely",
                                    evidence_quality="Strong")]) if primary == "internal" else \
             Causes(market=[Cause(claim="m", evidence_ids=["L1"], likelihood="Likely",
                                  evidence_quality="Strong")])
    return AttributionHypothesis(main_story="x",
                                 confidence=Confidence(likelihood="Likely", evidence_quality=eq),
                                 causes=causes)


def test_full_agreement_is_one():
    assert consistency_score([_h("internal"), _h("internal"), _h("internal")]) == 1.0


def test_disagreement_downgrades_and_notes_gap():
    samples = [_h("internal", "Strong"), _h("market"), _h("internal")]  # 2/3 agree
    h = apply_gate(_h("internal", "Strong"), samples, threshold=0.8)     # 0.67 < 0.8 -> downgrade
    assert h.confidence.evidence_quality == "Moderate"
    assert any("self-consistency" in g.lower() for g in h.assumptions_and_gaps)


def test_above_threshold_no_change():
    samples = [_h("internal"), _h("internal"), _h("internal")]
    h = apply_gate(_h("internal", "Strong"), samples, threshold=0.67)
    assert h.confidence.evidence_quality == "Strong"
