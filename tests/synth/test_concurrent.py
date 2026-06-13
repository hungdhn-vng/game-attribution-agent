"""Tests for concurrent N-sample synthesis (Task A7)."""
import pytest
from gaa.synth.concurrent import sample_concurrently
from gaa.synth.synthesizer import Synthesizer
from gaa.llm.client import FakeLLM
from gaa.schema.hypothesis import AttributionHypothesis
from gaa.schema.ledger import EvidenceLedger


def _ledger():
    led = EvidenceLedger()
    led.add(module="anomaly", claim="dau -40%", value="-0.40", source="internal:dau",
            source_type="internal", strength="high")
    return led


def _valid_preset():
    return {
        "main_story": "Internal issue.",
        "causes": {
            "internal": [{"claim": "v3.2 hurt retention", "evidence_ids": ["L1"],
                          "likelihood": "Likely"}],
            "market": [],
        },
        "scenarios": [],
        "risks": [],
        "assumptions_and_gaps": [],
    }


def test_sample_concurrently_n3_returns_3_hypotheses():
    synth = Synthesizer(FakeLLM(_valid_preset()))
    results = sample_concurrently(synth, _ledger(), "why down?", n=3)
    assert len(results) == 3
    assert all(isinstance(h, AttributionHypothesis) for h in results)


def test_sample_concurrently_n1_returns_1_hypothesis():
    synth = Synthesizer(FakeLLM(_valid_preset()))
    results = sample_concurrently(synth, _ledger(), "why down?", n=1)
    assert len(results) == 1
    assert isinstance(results[0], AttributionHypothesis)


def test_sample_concurrently_n1_skips_executor():
    """n=1 should not use ThreadPoolExecutor — just direct call."""
    synth = Synthesizer(FakeLLM(_valid_preset()))
    results = sample_concurrently(synth, _ledger(), "q", n=1)
    assert len(results) == 1


def test_sample_concurrently_drops_failing_synths():
    """A synth that raises on some calls should have those calls dropped."""

    class FlakyLLM:
        """Returns invalid JSON (not a dict) to trigger failure in synthesizer."""
        def __init__(self):
            self._calls = 0

        def complete_json(self, system: str, user: str) -> dict:
            self._calls += 1
            if self._calls % 2 == 0:
                # Return something that causes _assemble to fail hard
                raise RuntimeError("simulated LLM error")
            return dict(_valid_preset())

    class FlakySynth:
        """Synthesizer whose synthesize raises on even-numbered calls."""
        def __init__(self):
            self._calls = 0

        def synthesize(self, ledger, query):
            self._calls += 1
            if self._calls % 2 == 0:
                raise RuntimeError("simulated synth error")
            synth = Synthesizer(FakeLLM(_valid_preset()))
            return synth.synthesize(ledger, query)

    results = sample_concurrently(FlakySynth(), _ledger(), "q", n=4)
    # calls 1, 3 succeed; calls 2, 4 fail → 2 results
    assert len(results) == 2
    assert all(isinstance(h, AttributionHypothesis) for h in results)


def test_sample_concurrently_all_fail_returns_empty():
    """When every call raises, return empty list."""

    class AlwaysFailSynth:
        def synthesize(self, ledger, query):
            raise RuntimeError("always fail")

    results = sample_concurrently(AlwaysFailSynth(), _ledger(), "q", n=3)
    assert results == []
