from __future__ import annotations

import re

import pandas as pd

from gaa.core.ingest.detect import IngestError
from gaa.core.schema.canonical import validate_canonical
from gaa.core.schema.ingest_plan import IngestionPlan

# strip thousands separators, currency symbols, percent signs, whitespace before float cast
_NUM_JUNK = re.compile(r"[,$€£%\s]")


def _to_float(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.replace(_NUM_JUNK, "", regex=True).replace("", None)
    return pd.to_numeric(cleaned, errors="coerce")


class PlanAdapter:
    """Execute an IngestionPlan against a raw DataFrame → canonical long frame."""

    def load(self, df: pd.DataFrame, plan: IngestionPlan) -> pd.DataFrame:
        try:
            long = self._wide(df, plan) if plan.orientation == "wide" else self._long(df, plan)
        except KeyError as exc:
            raise IngestError("plan_mismatch", f"column {exc} not found in the file",
                              "the file's columns don't match the plan — re-propose") from exc
        long["value"] = _to_float(long["value"])
        if bool(long["value"].isna().all()):
            raise IngestError("bad_values", "no numeric values after coercion",
                              "check that the value column(s) hold numbers")
        long = long.dropna(subset=["value"])
        return validate_canonical(long)

    def _wide(self, df: pd.DataFrame, plan: IngestionPlan) -> pd.DataFrame:
        id_vars = [plan.date_col] + list(plan.dim_cols.keys())
        value_vars = list(plan.metric_cols.keys())
        missing = [c for c in id_vars + value_vars if c not in df.columns]
        if missing:
            raise KeyError(missing[0])
        long = df.melt(id_vars=id_vars, value_vars=value_vars,
                       var_name="_src_metric", value_name="value")
        long["metric"] = long["_src_metric"].map(plan.metric_cols)
        long = long.drop(columns=["_src_metric"]).rename(
            columns={plan.date_col: "date", **plan.dim_cols})
        return long

    def _long(self, df: pd.DataFrame, plan: IngestionPlan) -> pd.DataFrame:
        keep = [plan.date_col, plan.long_metric_col, plan.long_value_col] + list(plan.dim_cols.keys())
        missing = [c for c in keep if c not in df.columns]
        if missing:
            raise KeyError(missing[0])
        return df[keep].rename(columns={
            plan.date_col: "date", plan.long_metric_col: "metric",
            plan.long_value_col: "value", **plan.dim_cols})
