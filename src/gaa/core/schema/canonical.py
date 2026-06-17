import pandas as pd

REQUIRED_COLUMNS = ["date", "metric", "value"]
CANONICAL_DIMS = ["platform", "region", "version", "cohort", "device", "source"]
ALL_COLUMNS = REQUIRED_COLUMNS + CANONICAL_DIMS

_NON_DIM = set(REQUIRED_COLUMNS)


def dim_columns(df: pd.DataFrame) -> list[str]:
    """All dimension columns present: canonical dims first (in canonical order),
    then any extra/custom dims (sorted), excluding date/metric/value."""
    present = [c for c in CANONICAL_DIMS if c in df.columns]
    extra = sorted(c for c in df.columns if c not in _NON_DIM and c not in CANONICAL_DIMS)
    return present + extra


def empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=ALL_COLUMNS)


def validate_canonical(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"canonical frame missing required columns: {missing}")
    out = df.copy()
    # Parse to UTC then drop the tz: some exports carry a 'Z' suffix (tz-aware), but every
    # downstream comparison builds tz-naive Timestamps; a tz-aware column matches zero rows.
    out["date"] = pd.to_datetime(out["date"], errors="raise", utc=True).dt.tz_localize(None)
    out["value"] = out["value"].astype(float)
    out["metric"] = out["metric"].astype(str)
    # Extra (custom) dims are any column that isn't required + isn't a canonical dim.
    extra_dims = [c for c in out.columns if c not in ALL_COLUMNS]
    for dim in CANONICAL_DIMS + extra_dims:
        if dim not in out.columns:
            out[dim] = None
        else:
            # dims are categorical labels → strings (keep null as None so "3.10" != "3.1")
            out[dim] = out[dim].map(lambda x: str(x) if pd.notna(x) else None)
    return out[REQUIRED_COLUMNS + CANONICAL_DIMS + extra_dims]
