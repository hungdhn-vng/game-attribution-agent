import json
from gaa.sources.roblox_benchmark import RoMonitorBenchmark

CANNED = json.dumps({"points": [
    {"date": "2026-05-01", "ccu": 5000},
    {"date": "2026-05-02", "ccu": 4900},
    {"date": "2026-05-03", "ccu": 4800}]})


def test_genre_trend_indexes_to_100(tmp_path):
    src = RoMonitorBenchmark(cache_dir=str(tmp_path), fetch_fn=lambda url: CANNED,
                             genre_url_tmpl="http://romon/{genre}.json")
    trend = src.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert trend["2026-05-01"] == 100.0
    assert round(trend["2026-05-03"], 1) == 96.0  # 4800/5000*100


def test_empty_payload_returns_empty(tmp_path):
    src = RoMonitorBenchmark(cache_dir=str(tmp_path), fetch_fn=lambda url: '{"points": []}',
                             genre_url_tmpl="http://romon/{genre}.json")
    assert src.genre_trend("survival", "2026-05-01", "2026-05-03") == {}
