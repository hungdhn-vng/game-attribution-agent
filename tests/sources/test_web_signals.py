import json
from gaa.sources.web_signals import WebSignalsSource

CANNED = json.dumps([
    {"date": "2026-05-04", "title": "v3.2 update", "kind": "patch",
     "url": "http://p", "sentiment": -0.1},
    {"date": "2026-06-30", "title": "out of window", "kind": "news",
     "url": "http://n", "sentiment": 0.0}])


def test_events_filtered_to_window(tmp_path):
    src = WebSignalsSource(cache_dir=str(tmp_path), fetch_fn=lambda url: CANNED,
                           query_url_tmpl="http://news?q={game}")
    evs = src.events("MyGame", "survival", "2026-05-01", "2026-05-31")
    assert len(evs) == 1 and evs[0]["kind"] == "patch"
