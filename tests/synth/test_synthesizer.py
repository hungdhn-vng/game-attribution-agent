from gaa.synth.synthesizer import Synthesizer
from gaa.llm.client import FakeLLM
from gaa.schema.ledger import EvidenceLedger


def _ledger():
    led = EvidenceLedger()
    led.add(module="anomaly", claim="dau -40%", value="-0.40", source="internal:dau",
            source_type="internal", strength="high")
    led.add(module="market", claim="genre flat", value="-0.03", source="benchmark",
            source_type="external", strength="med")
    return led


def test_computes_evidence_quality_from_citations():
    preset = {
        "main_story": "Mostly internal.",
        "causes": {
            "internal": [{"claim": "v3.2 hurt retention", "evidence_ids": ["L1"],
                          "likelihood": "Likely"}],
            "market": [{"claim": "genre flat rules out market", "evidence_ids": ["L1", "L2"],
                        "likelihood": "Possible"}],
        },
        "scenarios": [{"description": "hotfix recovers", "likelihood": "Likely",
                       "evidence_ids": ["L1"], "signals_to_watch": ["D7 retention"]}],
        "risks": [{"description": "acq cut", "likelihood": "Possible", "evidence_ids": []}],
        "assumptions_and_gaps": ["no UA data"],
    }
    h = Synthesizer(FakeLLM(preset)).synthesize(_ledger(), query="why down?")
    # internal cause cites only L1 (internal,high) -> score 1+1=2 -> Moderate
    assert h.causes.internal[0].evidence_quality == "Moderate"
    # market cause cites L1+L2 (internal+external, one high) -> 2+2+1=5 -> Strong
    assert h.causes.market[0].evidence_quality == "Strong"
    assert len(h.evidence) == 2  # full ledger attached
    assert h.main_story == "Mostly internal."


def test_headline_confidence_present():
    h = Synthesizer(FakeLLM({
        "main_story": "x", "causes": {"internal": [], "market": []},
        "scenarios": [], "risks": [], "assumptions_and_gaps": []})).synthesize(_ledger(), "q")
    assert h.confidence.likelihood in ("Very likely", "Likely", "Possible", "Unlikely")


def test_tolerates_llm_key_variations():
    """Live Qwen sometimes omits 'description' or uses alt keys / string signals — must not crash."""
    led = _ledger()
    preset = {
        "main_story": "ok",
        "causes": {"internal": [{"cause": "alt-key cause", "evidence": ["L1"]}],
                   "market": [{"claim": "", "evidence_ids": ["L2"]}]},   # empty claim → dropped
        "scenarios": [{"scenario": "alt-key scenario", "signals": "watch this"},
                      {"likelihood": "Likely"}],                          # no text → dropped
        "risks": [{"text": "risk via text"}, {"foo": "bar"}],             # second dropped
        "assumptions_and_gaps": [],
    }
    h = Synthesizer(FakeLLM(preset)).synthesize(led, "q")
    assert h.causes.internal[0].claim == "alt-key cause"
    assert h.causes.internal[0].evidence_ids == ["L1"]
    assert h.causes.market == []                       # empty-claim cause dropped
    assert [s.description for s in h.scenarios] == ["alt-key scenario"]
    assert h.scenarios[0].signals_to_watch == ["watch this"]
    assert [r.description for r in h.risks] == ["risk via text"]
