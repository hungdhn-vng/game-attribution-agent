from gaa.llm.client import LLM
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.hypothesis import (
    AttributionHypothesis, Cause, Scenario, Risk, Causes)
from gaa.schema.confidence import Confidence
from gaa.confidence import evidence_quality

SYSTEM = (
    "You are a game-data attribution analyst. Separate INTERNAL causes (the game's own "
    "updates, segments, monetization) from MARKET causes (genre-wide trends, seasonality, "
    "competitors). Present scenarios, never prescribe decisions. Ground every claim in the "
    "provided evidence ids; if evidence is thin, say so in assumptions_and_gaps. "
    "Return JSON with keys: main_story, causes{internal[],market[]}, scenarios[], risks[], "
    "assumptions_and_gaps[]. Each cause/scenario item has claim/description, evidence_ids[], "
    "and likelihood in {Very likely,Likely,Possible,Unlikely}. Do NOT output evidence_quality."
)


def _ledger_brief(ledger: EvidenceLedger) -> str:
    return "\n".join(
        f"{e.id} [{e.source_type}/{e.strength}] {e.claim} ({e.value}) src={e.source}"
        for e in ledger.all())


class Synthesizer:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def synthesize(self, ledger: EvidenceLedger, query: str) -> AttributionHypothesis:
        user = f"QUERY: {query}\n\nEVIDENCE LEDGER:\n{_ledger_brief(ledger)}"
        raw = self._llm.complete_json(SYSTEM, user)
        return self._assemble(raw, ledger)

    def _eq(self, ledger: EvidenceLedger, ids: list) -> str:
        return evidence_quality(ledger.by_ids(ids))

    def _cause(self, ledger, item) -> Cause:
        ids = item.get("evidence_ids", [])
        return Cause(claim=item["claim"], evidence_ids=ids,
                     likelihood=item.get("likelihood", "Possible"),
                     evidence_quality=self._eq(ledger, ids))

    def _assemble(self, raw: dict, ledger: EvidenceLedger) -> AttributionHypothesis:
        causes_raw = raw.get("causes", {})
        internal = [self._cause(ledger, c) for c in causes_raw.get("internal", [])]
        market = [self._cause(ledger, c) for c in causes_raw.get("market", [])]
        scenarios = [
            Scenario(description=s["description"],
                     likelihood=s.get("likelihood", "Possible"),
                     evidence_quality=self._eq(ledger, s.get("evidence_ids", [])),
                     signals_to_watch=s.get("signals_to_watch", []))
            for s in raw.get("scenarios", [])]
        risks = [
            Risk(description=r["description"],
                 likelihood=r.get("likelihood", "Possible"),
                 evidence_quality=self._eq(ledger, r.get("evidence_ids", [])))
            for r in raw.get("risks", [])]

        all_internal_ids = [i for c in internal for i in c.evidence_ids]
        headline_eq = self._eq(ledger, all_internal_ids) if all_internal_ids \
            else evidence_quality(ledger.all())
        headline_lk = internal[0].likelihood if internal else "Possible"

        return AttributionHypothesis(
            main_story=raw.get("main_story", ""),
            confidence=Confidence(likelihood=headline_lk, evidence_quality=headline_eq),
            causes=Causes(internal=internal, market=market),
            scenarios=scenarios, risks=risks,
            evidence=ledger.all(),
            assumptions_and_gaps=raw.get("assumptions_and_gaps", []),
        )
