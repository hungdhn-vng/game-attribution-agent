import io
import pytest
import pandas as pd
from gaa.core.ingest import detect
from gaa.core.ingest.detect import read_any, IngestError


def _xlsx() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"date": ["2026-05-01"], "dau": [5]}).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_routes_csv_by_default():
    rt = read_any(content=b"date,dau\n2026-05-01,1000\n", filename="x.csv")
    assert rt.read_spec.format == "csv"


def test_routes_excel_by_magic_and_extension():
    rt = read_any(content=_xlsx(), filename="report.xlsx")
    assert rt.read_spec.format == "excel"
    # magic-byte detection even without a helpful name
    rt2 = read_any(content=_xlsx(), filename="report.bin")
    assert rt2.read_spec.format == "excel"


def test_routes_json_by_content():
    rt = read_any(content=b'[{"date":"2026-05-01","dau":5}]', filename="d.json")
    assert rt.read_spec.format == "json"


def test_routes_paste_text():
    rt = read_any(text="date\tdau\n2026-05-01\t5\n")
    assert rt.read_spec.format == "paste"


def test_empty_content_raises_ingest_error():
    with pytest.raises(IngestError) as e:
        read_any(content=b"")
    assert e.value.code == "unreadable_file"


def test_reread_by_spec_uses_format():
    from gaa.core.schema.ingest_plan import ReadSpec
    rt = read_any(content=b"date;dau\n2026-05-01;5\n",
                  spec=ReadSpec(format="csv", delimiter=";"))
    assert list(rt.df.columns) == ["date", "dau"]
