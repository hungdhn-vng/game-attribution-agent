from __future__ import annotations

import io
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


def _pick_sheet(xls: pd.ExcelFile, spec: Optional[ReadSpec]) -> str:
    if spec and spec.sheet:
        return spec.sheet
    best, best_score = xls.sheet_names[0], -1
    for name in xls.sheet_names:
        probe = xls.parse(name, header=None, nrows=50)
        score = int(probe.notna().to_numpy().sum())
        if score > best_score:
            best, best_score = name, score
    return best


def _find_header_row(xls: pd.ExcelFile, sheet: str, spec: Optional[ReadSpec]) -> int:
    if spec is not None:
        return spec.header_row
    probe = xls.parse(sheet, header=None, nrows=20)
    for i in range(len(probe)):
        if int(probe.iloc[i].notna().sum()) >= 2:
            return i
    return 0


def read_excel_bytes(data: bytes, spec: Optional[ReadSpec] = None) -> RawTable:
    xls = pd.ExcelFile(io.BytesIO(data), engine="openpyxl")
    sheet = _pick_sheet(xls, spec)
    header_row = _find_header_row(xls, sheet, spec)
    df = xls.parse(sheet, header=header_row, keep_default_na=False, na_values=[""])
    df.columns = [str(c).strip() for c in df.columns]
    notes = []
    if len(xls.sheet_names) > 1:
        notes.append(f"selected sheet '{sheet}' of {xls.sheet_names}")
    rs = ReadSpec(format="excel", sheet=sheet, header_row=header_row)
    return RawTable(df=df, read_spec=rs, notes=notes)
