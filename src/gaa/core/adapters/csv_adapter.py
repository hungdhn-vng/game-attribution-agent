from typing import Union
import pandas as pd
from gaa.core.schema.profile import ColumnMapping
from gaa.core.schema.canonical import validate_canonical


class CSVAdapter:
    def load(self, raw: Union[str, pd.DataFrame], mapping: ColumnMapping) -> pd.DataFrame:
        # NA-safe read: keep_default_na=False so values like "NA" (North America)
        # survive instead of being parsed as NaN; only an empty cell is missing.
        raw_df = raw if isinstance(raw, pd.DataFrame) else pd.read_csv(
            raw, keep_default_na=False, na_values=[""])
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
