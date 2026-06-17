from gaa.core.ingest.readers.csv_reader import read_csv_bytes


def test_sniffs_semicolon_delimiter():
    data = b"date;dau;region\n2026-05-01;1000;SEA\n"
    rt = read_csv_bytes(data)
    assert list(rt.df.columns) == ["date", "dau", "region"]
    assert rt.read_spec.delimiter == ";"


def test_latin1_fallback():
    data = "date,city\n2026-05-01,São Paulo\n".encode("latin-1")
    rt = read_csv_bytes(data)
    assert rt.df.iloc[0]["city"] == "São Paulo"


def test_na_string_survives():
    data = b"date,region,dau\n2026-05-01,NA,1000\n"
    rt = read_csv_bytes(data)
    # "NA" (North America) must NOT become NaN
    assert rt.df.iloc[0]["region"] == "NA"


def test_respects_spec_delimiter_on_reread():
    from gaa.core.schema.ingest_plan import ReadSpec
    data = b"date;dau\n2026-05-01;5\n"
    rt = read_csv_bytes(data, ReadSpec(format="csv", delimiter=";"))
    assert list(rt.df.columns) == ["date", "dau"]
