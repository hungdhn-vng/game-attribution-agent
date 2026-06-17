from __future__ import annotations

import io
import re
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec

# a markdown separator row: only |, -, :, spaces
_MD_SEP = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")


def _read_markdown(lines: list[str]) -> pd.DataFrame:
    rows = []
    for ln in lines:
        if _MD_SEP.match(ln) and "-" in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    header, *body = rows
    return pd.DataFrame(body, columns=header)


def read_paste(text: str, spec: Optional[ReadSpec] = None) -> RawTable:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        df = pd.DataFrame()
    elif any("|" in ln for ln in lines[:2]):
        df = _read_markdown(lines)
    else:
        df = pd.read_csv(io.StringIO(text), sep=r"\t|\s{2,}", engine="python",
                         keep_default_na=False, na_values=[""])
    return RawTable(df=df, read_spec=ReadSpec(format="paste"), notes=[])
