from pydantic import BaseModel
from gaa.core.schema.confidence import Confidence, Likelihood, EvidenceQuality
from gaa.core.schema.ledger import LedgerEntry


class Cause(BaseModel):
    claim: str
    evidence_ids: list[str]
    likelihood: Likelihood
    evidence_quality: EvidenceQuality


class Scenario(BaseModel):
    description: str
    likelihood: Likelihood
    evidence_quality: EvidenceQuality
    signals_to_watch: list[str] = []


class Risk(BaseModel):
    description: str
    likelihood: Likelihood
    evidence_quality: EvidenceQuality


class Causes(BaseModel):
    internal: list[Cause] = []
    market: list[Cause] = []


class AttributionHypothesis(BaseModel):
    main_story: str
    confidence: Confidence
    causes: Causes
    scenarios: list[Scenario] = []
    risks: list[Risk] = []
    evidence: list[LedgerEntry] = []
    assumptions_and_gaps: list[str] = []
    rationale: str = ""
