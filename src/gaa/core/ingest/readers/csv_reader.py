from __future__ import annotations

import csv as _csv
import io
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec

_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1"]


def _decode(data: bytes, forced: Optional[str]) -> tuple[str, str]:
    if forced:
        return data.decode(forced, errors="replace"), forced
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"


def _sniff_delim(text: str) -> str:
    sample = "\n".join(text.splitlines()[:5])
    try:
        return _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        return ","


def read_csv_bytes(data: bytes, spec: Optional[ReadSpec] = None) -> RawTable:
    text, enc = _decode(data, spec.encoding if spec else None)
    delimiter = spec.delimiter if (spec and spec.delimiter) else _sniff_delim(text)
    header_row = spec.header_row if spec else 0
    df = pd.read_csv(io.StringIO(text), sep=delimiter, header=header_row,
                     keep_default_na=False, na_values=[""])
    rs = ReadSpec(format="csv", delimiter=delimiter, encoding=enc, header_row=header_row)
    return RawTable(df=df, read_spec=rs, notes=[])
