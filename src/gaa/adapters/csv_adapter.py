from typing import Union
import pandas as pd
from gaa.schema.profile import ColumnMapping
from gaa.schema.canonical import validate_canonical


class CSVAdapter:
    def load(self, raw: Union[str, pd.DataFrame], mapping: ColumnMapping) -> pd.DataFrame:
        raw_df = raw if isinstance(raw, pd.DataFrame) else pd.read_csv(raw)
        id_vars = [mapping.date_col] + list(mapping.dim_cols.keys())
        value_vars = list(mapping.metric_cols.keys())
        long = raw_df.melt(
            id_vars=id_vars, value_vars=value_vars,
            var_name="_src_metric", value_name="value",
        )
        long["metric"] = long["_src_metric"].map(mapping.metric_cols)
        long = long.rename(columns={mapping.date_col: "date", **mapping.dim_cols})
        long = long.drop(columns=["_src_metric"])
        return validate_canonical(long)
