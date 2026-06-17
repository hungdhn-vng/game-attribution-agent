from gaa.core.ingest.readers.json_reader import read_json_bytes


def test_json_array_of_records():
    data = b'[{"date":"2026-05-01","dau":1000},{"date":"2026-05-02","dau":1100}]'
    rt = read_json_bytes(data)
    assert list(rt.df.columns) == ["date", "dau"]
    assert len(rt.df) == 2
    assert rt.read_spec.format == "json"


def test_jsonl_records():
    data = b'{"date":"2026-05-01","dau":1000}\n{"date":"2026-05-02","dau":1100}\n'
    rt = read_json_bytes(data)
    assert len(rt.df) == 2
    assert rt.read_spec.format == "jsonl"


def test_json_object_with_nested_array():
    data = b'{"rows":[{"date":"2026-05-01","dau":5}]}'
    rt = read_json_bytes(data)
    assert rt.df.iloc[0]["dau"] == 5
