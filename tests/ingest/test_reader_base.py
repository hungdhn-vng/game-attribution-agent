import pandas as pd
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


def test_rawtable_holds_df_spec_notes():
    rt = RawTable(df=pd.DataFrame({"a": [1]}), read_spec=ReadSpec(format="csv"))
    assert list(rt.df.columns) == ["a"]
    assert rt.read_spec.format == "csv"
    assert rt.notes == []
