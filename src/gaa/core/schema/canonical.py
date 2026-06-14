import pandas as pd

REQUIRED_COLUMNS = ["date", "metric", "value"]
CANONICAL_DIMS = ["platform", "region", "version", "cohort", "device", "source"]
ALL_COLUMNS = REQUIRED_COLUMNS + CANONICAL_DIMS


def empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=ALL_COLUMNS)


def validate_canonical(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"canonical frame missing required columns: {missing}")
    out = df.copy()
    # Parse to UTC then drop the tz: Roblox exports carry a 'Z' suffix (tz-aware),
    # but every downstream comparison builds tz-naive Timestamps from date strings.
    # A tz-aware column silently matches zero rows, so normalize to tz-naive here.
    out["date"] = pd.to_datetime(out["date"], errors="raise", utc=True).dt.tz_localize(None)
    out["value"] = out["value"].astype(float)
    out["metric"] = out["metric"].astype(str)
    for dim in CANONICAL_DIMS:
        if dim not in out.columns:
            out[dim] = None
        else:
            # dims are categorical labels → strings (keep null as None so "3.10" != "3.1")
            out[dim] = out[dim].map(lambda x: str(x) if pd.notna(x) else None)
    return out[ALL_COLUMNS]
