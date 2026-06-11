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
    out["date"] = pd.to_datetime(out["date"], errors="raise")
    out["value"] = out["value"].astype(float)
    out["metric"] = out["metric"].astype(str)
    for dim in CANONICAL_DIMS:
        if dim not in out.columns:
            out[dim] = None
    return out[ALL_COLUMNS]
