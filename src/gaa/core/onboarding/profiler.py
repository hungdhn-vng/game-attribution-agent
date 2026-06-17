import pandas as pd

from gaa.core.llm.client import LLM
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import IngestionPlan

SYSTEM = (
    "You map a game-metrics table to a canonical long schema.\n"
    "Canonical metric names: dau, mau, revenue, arppu, retention_d1, retention_d7, "
    "retention_d30, sessions, playtime. Canonical dimensions: platform, region, "
    "version, cohort, device, source.\n"
    "Decide orientation: 'wide' if each metric is its own column; 'long' if one column "
    "holds metric names and another holds the values.\n"
    "Map a column to a canonical name ONLY when it clearly fits; otherwise KEEP the "
    "column under a normalized snake_case name — do NOT drop columns you don't recognize.\n"
    "Return ONE JSON object: {orientation, date_col, "
    "metric_cols:{source_col->final_metric_name}, long_metric_col, long_value_col, "
    "dim_cols:{source_col->dim_name}, confidence (0.0-1.0), notes:[strings]}. "
    "For wide tables fill metric_cols and leave long_* null; for long tables fill "
    "long_metric_col + long_value_col and leave metric_cols empty. "
    "confidence reflects how sure you are about orientation, the date column, and the mappings."
)


class Profiler:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def propose(self, raw: RawTable) -> IngestionPlan:
        cols = list(raw.df.columns)
        head = raw.df.head(5).astype(str).to_dict(orient="records")
        user = f"COLUMNS: {cols}\nSAMPLE ROWS: {head}"
        fields = self._llm.complete_json(SYSTEM, user)
        fields.pop("read_spec", None)  # read_spec is authoritative from the reader
        return IngestionPlan(read_spec=raw.read_spec, **fields)

    def summary(self, plan: IngestionPlan, preview: pd.DataFrame) -> str:
        if plan.orientation == "wide":
            cols = ", ".join(f"{s} → {n}" for s, n in plan.metric_cols.items())
            shape = f"wide layout; metrics: {cols}"
        else:
            shape = (f"long layout; metric names in `{plan.long_metric_col}`, "
                     f"values in `{plan.long_value_col}`")
        dims = ", ".join(f"{s} → {n}" for s, n in plan.dim_cols.items()) or "(none)"
        note_line = ("\n• notes: " + "; ".join(plan.notes)) if plan.notes else ""
        return (
            f"I read this as a {plan.read_spec.format} file:\n"
            f"• date = `{plan.date_col}`\n"
            f"• {shape}\n"
            f"• dimensions: {dims}\n"
            f"• confidence: {plan.confidence:.0%}{note_line}\n\n"
            f"Preview:\n{preview.head(5).to_string(index=False)}\n\n"
            f"Reply 'confirm' to save, or tell me what to fix."
        )
