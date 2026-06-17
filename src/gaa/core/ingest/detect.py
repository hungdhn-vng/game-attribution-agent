from __future__ import annotations

import os
from typing import Optional

from gaa.core.ingest.readers import csv_reader, excel_reader, json_reader, paste_reader
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


class IngestError(Exception):
    """A structured, user-facing ingestion failure."""
    def __init__(self, code: str, detail: str = "", hint: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.hint = hint

    def as_dict(self) -> dict:
        return {"status": "error", "error": self.code,
                "detail": self.detail, "hint": self.hint}


_XLSX_MAGIC = b"PK\x03\x04"
_SUPPORTED = "supported: CSV/TSV, Excel (.xlsx), JSON/JSONL, or a pasted table"


def _detect_format(data: bytes, filename: Optional[str]) -> str:
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    if ext in (".xlsx", ".xlsm", ".xls"):
        return "excel"
    if ext == ".json":
        return "json"
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if data[:4] == _XLSX_MAGIC:
        return "excel"
    head = data[:64].lstrip()
    if head[:1] in (b"{", b"["):
        return "json"
    return "csv"


def _read_by_format(fmt: str, content: Optional[bytes], text: Optional[str],
                    spec: Optional[ReadSpec]) -> RawTable:
    try:
        if fmt == "paste":
            body = text if text is not None else (content or b"").decode("utf-8", "replace")
            return paste_reader.read_paste(body, spec)
        if fmt == "excel":
            return excel_reader.read_excel_bytes(content, spec)
        if fmt in ("json", "jsonl"):
            return json_reader.read_json_bytes(content, spec)
        return csv_reader.read_csv_bytes(content, spec)
    except IngestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IngestError("unreadable_file", str(exc), _SUPPORTED) from exc


def read_any(*, content: Optional[bytes] = None, filename: Optional[str] = None,
             text: Optional[str] = None, spec: Optional[ReadSpec] = None) -> RawTable:
    """Single entrypoint. With `spec`, re-read deterministically by its format.
    Otherwise detect from `text` (paste) or `content`+`filename`."""
    if spec is not None:
        return _read_by_format(spec.format, content, text, spec)
    if text is not None:
        return _read_by_format("paste", None, text, None)
    if not content:
        raise IngestError("unreadable_file", "no content provided",
                          "attach a file or paste a table — " + _SUPPORTED)
    return _read_by_format(_detect_format(content, filename), content, text, None)
