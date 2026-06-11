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
    "Return JSON with keys: main_story, rationale, causes{internal[],market[]}, scenarios[], "
    "risks[], assumptions_and_gaps[]. rationale is a 1-2 sentence explanation of your reasoning. "
    "Each cause/scenario item has claim/description, evidence_ids[], "
    "and likelihood in {Very likely,Likely,Possible,Unlikely}. Do NOT output evidence_quality. "
    "assumptions_and_gaps is an array of plain strings (one short sentence each), NOT objects."
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

    @staticmethod
    def _text(item: dict, *keys: str) -> str:
        for k in keys:
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""

    @staticmethod
    def _watch(item: dict) -> list:
        v = item.get("signals_to_watch") or item.get("signals") or []
        return [v] if isinstance(v, str) else (v if isinstance(v, list) else [])

    @staticmethod
    def _gap(item) -> str:
        # Qwen sometimes emits each gap as an object {claim, evidence_ids, likelihood}
        # instead of a plain string; coerce to the schema's list[str] like every sibling field.
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            return Synthesizer._text(item, "claim", "text", "description", "gap", "assumption", "note")
        return ""

    def _cause(self, ledger, item):
        if not isinstance(item, dict):
            return None
        claim = self._text(item, "claim", "cause", "description", "text")
        if not claim:
            return None
        ids = item.get("evidence_ids") or item.get("evidence") or []
        ids = [str(i) for i in ids] if isinstance(ids, list) else []
        return Cause(claim=claim, evidence_ids=ids,
                     likelihood=item.get("likelihood", "Possible"),
                     evidence_quality=self._eq(ledger, ids))

    def _assemble(self, raw: dict, ledger: EvidenceLedger) -> AttributionHypothesis:
        causes_raw = raw.get("causes")
        if not isinstance(causes_raw, dict):
            causes_raw = {}
        internal = [c for c in (self._cause(ledger, x) for x in (causes_raw.get("internal") or [])) if c]
        market = [c for c in (self._cause(ledger, x) for x in (causes_raw.get("market") or [])) if c]
        scenarios = []
        for s in (raw.get("scenarios") or []):
            if not isinstance(s, dict):
                continue
            desc = self._text(s, "description", "scenario", "text", "claim")
            if not desc:
                continue
            scenarios.append(Scenario(description=desc, likelihood=s.get("likelihood", "Possible"),
                                      evidence_quality=self._eq(ledger, s.get("evidence_ids") or []),
                                      signals_to_watch=self._watch(s)))
        risks = []
        for r in (raw.get("risks") or []):
            if not isinstance(r, dict):
                continue
            desc = self._text(r, "description", "risk", "text", "claim")
            if not desc:
                continue
            risks.append(Risk(description=desc, likelihood=r.get("likelihood", "Possible"),
                              evidence_quality=self._eq(ledger, r.get("evidence_ids") or [])))

        all_internal_ids = [i for c in internal for i in c.evidence_ids]
        headline_eq = self._eq(ledger, all_internal_ids) if all_internal_ids \
            else evidence_quality(ledger.all())
        headline_lk = internal[0].likelihood if internal else "Possible"

        return AttributionHypothesis(
            main_story=raw.get("main_story", ""),
            rationale=raw.get("rationale", ""),
            confidence=Confidence(likelihood=headline_lk, evidence_quality=headline_eq),
            causes=Causes(internal=internal, market=market),
            scenarios=scenarios, risks=risks,
            evidence=ledger.all(),
            assumptions_and_gaps=[g for g in (self._gap(x) for x in (raw.get("assumptions_and_gaps") or [])) if g],
        )
