from gaa.schema.ledger import EvidenceLedger
from gaa.synth.synthesizer import Synthesizer, SYSTEM


class CaptureLLM:
    def __init__(self):
        self.system = None

    def complete_json(self, system, user):
        self.system = system
        return {"main_story": "s", "rationale": "", "causes": {},
                "scenarios": [], "risks": [], "assumptions_and_gaps": []}


def test_no_provider_keeps_system_unchanged():
    llm = CaptureLLM()
    Synthesizer(llm).synthesize(EvidenceLedger(), "q")
    assert llm.system == SYSTEM


def test_instructions_appended_when_present():
    llm = CaptureLLM()
    Synthesizer(llm, instructions_provider=lambda: "Answer in Vietnamese.") \
        .synthesize(EvidenceLedger(), "q")
    assert llm.system.startswith(SYSTEM)
    assert "OPERATOR PREFERENCES" in llm.system
    assert "Answer in Vietnamese." in llm.system


def test_blank_instructions_ignored():
    llm = CaptureLLM()
    Synthesizer(llm, instructions_provider=lambda: "  ").synthesize(EvidenceLedger(), "q")
    assert llm.system == SYSTEM
