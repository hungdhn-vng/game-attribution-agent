import json
from gaa.core.sources.seeded_benchmark import SeededBenchmarkSource


def test_indexes_genre_series(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"survival": {"2026-05-01": 5000, "2026-05-02": 4950, "2026-05-03": 4900}}))
    src = SeededBenchmarkSource(str(seed))
    t = src.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert t["2026-05-01"] == 100.0
    assert round(t["2026-05-03"], 1) == 98.0


def test_falls_back_to_default_genre(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"_default": {"2026-05-01": 100, "2026-05-02": 99}}))
    src = SeededBenchmarkSource(str(seed))
    assert src.genre_trend("unknown-genre", "2026-05-01", "2026-05-02")["2026-05-01"] == 100.0


def test_missing_file_returns_empty(tmp_path):
    src = SeededBenchmarkSource(str(tmp_path / "nope.json"))
    assert src.genre_trend("survival", "2026-05-01", "2026-05-03") == {}
