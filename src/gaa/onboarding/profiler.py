import pandas as pd
from gaa.llm.client import LLM
from gaa.schema.profile import ColumnMapping

SYSTEM = (
    "Map a game-metrics table to a canonical schema. Canonical metric names include: "
    "dau, mau, revenue, arppu, retention_d1, retention_d7, retention_d30, sessions, playtime. "
    "Canonical dimensions: platform, region, version, cohort, device, source. "
    "Return JSON: {date_col, metric_cols:{source_col->canonical_metric}, "
    "dim_cols:{source_col->canonical_dim}}. Only include columns you are confident about."
)


class Profiler:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def propose(self, sample: pd.DataFrame) -> ColumnMapping:
        cols = list(sample.columns)
        head = sample.head(5).astype(str).to_dict(orient="records")
        user = f"COLUMNS: {cols}\nSAMPLE ROWS: {head}"
        raw = self._llm.complete_json(SYSTEM, user)
        return ColumnMapping(**raw)

    def confirmation_message(self, mapping: ColumnMapping) -> str:
        metrics = ", ".join(f"{s} → {c}" for s, c in mapping.metric_cols.items())
        dims = ", ".join(f"{s} → {c}" for s, c in mapping.dim_cols.items()) or "(none)"
        return (f"I read your data as:\n• date = `{mapping.date_col}`\n"
                f"• metrics: {metrics}\n• dimensions: {dims}\n"
                f"Reply 'confirm' to save, or tell me what to fix.")
