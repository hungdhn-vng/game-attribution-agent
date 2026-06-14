import pandas as pd
import pytest
from gaa.core.schema.canonical import (
    CANONICAL_DIMS, REQUIRED_COLUMNS, validate_canonical, empty_canonical,
)


def test_constants():
    assert REQUIRED_COLUMNS == ["date", "metric", "value"]
    assert "region" in CANONICAL_DIMS and "version" in CANONICAL_DIMS


def test_empty_has_all_columns():
    df = empty_canonical()
    for c in REQUIRED_COLUMNS + CANONICAL_DIMS:
        assert c in df.columns


def test_validate_accepts_good_frame():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-02"]),
        "metric": ["dau", "dau"],
        "value": [100.0, 90.0],
    })
    out = validate_canonical(df)
    assert list(out["metric"]) == ["dau", "dau"]
    assert "region" in out.columns  # missing dims backfilled


def test_validate_rejects_missing_required():
    df = pd.DataFrame({"metric": ["dau"], "value": [1.0]})
    with pytest.raises(ValueError, match="date"):
        validate_canonical(df)


def test_validate_coerces_types():
    df = pd.DataFrame({"date": ["2026-05-01"], "metric": ["dau"], "value": ["100"]})
    out = validate_canonical(df)
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert out["value"].dtype == float


def test_validate_normalizes_tz_aware_dates_to_naive():
    # Roblox exports carry a trailing 'Z' -> pandas parses tz-aware UTC. Downstream
    # comparisons build tz-naive Timestamps, so a tz-aware column silently matches
    # zero rows. The canonical boundary must normalize to tz-naive.
    df = pd.DataFrame({
        "date": ["2026-06-03T00:00:00.000Z", "2026-06-04T00:00:00.000Z"],
        "metric": ["retention_d1", "retention_d1"],
        "value": [0.02, 0.03],
    })
    out = validate_canonical(df)
    assert out["date"].dt.tz is None, "canonical 'date' must be tz-naive"
    # a naive Timestamp built from a date string must match a stored row
    assert (out["date"] == pd.Timestamp("2026-06-03")).sum() == 1
