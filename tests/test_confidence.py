from gaa.core.schema.ledger import LedgerEntry
from gaa.core.confidence import evidence_quality


def _e(stype, strength):
    return LedgerEntry(id="L", module="m", claim="c", value="v",
                       source="s", source_type=stype, strength=strength)


def test_empty_is_weak():
    assert evidence_quality([]) == "Weak"


def test_internal_and_external_agreement_is_strong():
    entries = [_e("internal", "high"), _e("external", "high"), _e("derived", "med")]
    assert evidence_quality(entries) == "Strong"


def test_single_medium_internal_is_weak():
    assert evidence_quality([_e("internal", "med")]) == "Weak"


def test_two_sources_one_high_is_moderate():
    assert evidence_quality([_e("internal", "high"), _e("derived", "low")]) == "Moderate"
