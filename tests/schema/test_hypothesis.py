from gaa.schema.confidence import Confidence, LIKELIHOODS, EVIDENCE_QUALITIES
from gaa.schema.hypothesis import Cause, Scenario, Risk, AttributionHypothesis


def test_enums():
    assert LIKELIHOODS == ("Very likely", "Likely", "Possible", "Unlikely")
    assert EVIDENCE_QUALITIES == ("Strong", "Moderate", "Weak")


def test_confidence_validates_members():
    c = Confidence(likelihood="Likely", evidence_quality="Moderate")
    assert c.likelihood == "Likely"
    import pytest
    with pytest.raises(ValueError):
        Confidence(likelihood="Maybe", evidence_quality="Moderate")


def test_hypothesis_roundtrip():
    h = AttributionHypothesis(
        main_story="x",
        confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes={"internal": [Cause(claim="a", evidence_ids=["L1"],
                                   likelihood="Likely", evidence_quality="Strong")],
                "market": []},
        scenarios=[Scenario(description="s", likelihood="Possible",
                            evidence_quality="Weak", signals_to_watch=["x"])],
        risks=[Risk(description="r", likelihood="Possible", evidence_quality="Weak")],
        evidence=[],
        assumptions_and_gaps=["no UA data"],
    )
    assert AttributionHypothesis(**h.model_dump()).main_story == "x"
