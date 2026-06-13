from typing import Optional, Union
import pandas as pd
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.schema.profile import ColumnMapping

DEFAULT_ROBLOX_MAPPING = ColumnMapping(
    date_col="Date",
    metric_cols={
        "DAU": "dau",
        "D1 Retention": "retention_d1",
        "D7 Retention": "retention_d7",
        "Revenue": "revenue",
    },
    dim_cols={"Platform": "platform", "Country": "region"},
)


class RobloxAdapter:
    def __init__(self) -> None:
        self._csv = CSVAdapter()

    def load(self, raw: Union[str, pd.DataFrame],
             mapping: Optional[ColumnMapping] = None) -> pd.DataFrame:
        return self._csv.load(raw, mapping or DEFAULT_ROBLOX_MAPPING)
