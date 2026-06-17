import io
import pandas as pd
from gaa.core.ingest.readers.excel_reader import read_excel_bytes


def _xlsx_with_title_row() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # row 0 is a title; the real header is on row 1
        df = pd.DataFrame([["Q2 Metrics Export", None, None],
                           ["date", "dau", "region"],
                           ["2026-05-01", 1000, "SEA"]])
        df.to_excel(xw, index=False, header=False, sheet_name="Data")
        pd.DataFrame({"junk": [None]}).to_excel(xw, index=False, sheet_name="Notes")
    return buf.getvalue()


def test_finds_header_row_and_picks_tabular_sheet():
    rt = read_excel_bytes(_xlsx_with_title_row())
    assert rt.read_spec.sheet == "Data"
    assert list(rt.df.columns) == ["date", "dau", "region"]
    assert rt.df.iloc[0]["region"] == "SEA"
    assert rt.read_spec.header_row == 1


def test_reread_with_spec_is_stable():
    from gaa.core.schema.ingest_plan import ReadSpec
    data = _xlsx_with_title_row()
    rt = read_excel_bytes(data, ReadSpec(format="excel", sheet="Data", header_row=1))
    assert list(rt.df.columns) == ["date", "dau", "region"]
