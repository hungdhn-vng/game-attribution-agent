from gaa.runs.slug import slugify_query, make_run_id


def test_slugify_drops_stopwords_and_limits_words():
    assert slugify_query("why did my revenue drop last week?") == "revenue-drop"


def test_slugify_handles_empty_after_stopwords():
    assert slugify_query("why did it?") == "analysis"


def test_make_run_id_is_deterministic_with_explicit_suffix():
    rid = make_run_id("why did revenue drop?", today="2026-06-13", suffix="k3f9")
    assert rid == "2026-06-13-revenue-drop-k3f9"


def test_make_run_id_generates_4char_suffix_when_omitted():
    rid = make_run_id("revenue analysis", today="2026-06-13")
    parts = rid.split("-")
    assert parts[:3] == ["2026", "06", "13"]
    assert len(parts[-1]) == 4
