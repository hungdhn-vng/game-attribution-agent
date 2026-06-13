from typing import Literal
from pydantic import BaseModel

LIKELIHOODS = ("Very likely", "Likely", "Possible", "Unlikely")
EVIDENCE_QUALITIES = ("Strong", "Moderate", "Weak")

Likelihood = Literal["Very likely", "Likely", "Possible", "Unlikely"]
EvidenceQuality = Literal["Strong", "Moderate", "Weak"]


class Confidence(BaseModel):
    likelihood: Likelihood
    evidence_quality: EvidenceQuality
