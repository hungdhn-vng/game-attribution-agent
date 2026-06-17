from gaa.core.ingest.readers.paste_reader import read_paste


def test_markdown_table():
    text = (
        "| date       | dau  | region |\n"
        "|------------|------|--------|\n"
        "| 2026-05-01 | 1000 | SEA    |\n"
        "| 2026-05-02 | 1100 | SEA    |\n"
    )
    rt = read_paste(text)
    assert list(rt.df.columns) == ["date", "dau", "region"]
    assert len(rt.df) == 2
    assert rt.df.iloc[0]["region"] == "SEA"
    assert rt.read_spec.format == "paste"


def test_tab_separated_paste():
    text = "date\tdau\n2026-05-01\t1000\n2026-05-02\t1100\n"
    rt = read_paste(text)
    assert list(rt.df.columns) == ["date", "dau"]
    assert len(rt.df) == 2
