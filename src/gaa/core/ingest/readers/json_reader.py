from __future__ import annotations

import json
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


def _looks_jsonl(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    try:
        json.loads(lines[0])
        json.loads(lines[1])
        return True
    except Exception:
        return False


def _records(text: str, fmt: Optional[str]) -> tuple[list, str]:
    if fmt == "jsonl" or (fmt is None and _looks_jsonl(text)):
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()], "jsonl"
    obj = json.loads(text)
    if isinstance(obj, list):
        return obj, "json"
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list):
                return v, "json"
        return [obj], "json"
    return [obj], "json"


def read_json_bytes(data: bytes, spec: Optional[ReadSpec] = None) -> RawTable:
    text = data.decode("utf-8", errors="replace")
    records, fmt = _records(text, spec.format if spec else None)
    df = pd.json_normalize(records)
    return RawTable(df=df, read_spec=ReadSpec(format=fmt), notes=[])
