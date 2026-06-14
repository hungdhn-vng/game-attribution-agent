from gaa.core.crawl.roblox_title import universe_id_from, lookup_universe_title


def test_extracts_universe_id_from_csv_key():
    assert universe_id_from("Universe-9980885306- Day 1 retention …") == "9980885306"
    assert universe_id_from("no id here") is None


def test_lookup_uses_injected_fetcher():
    body = '{"data": [{"name": "[ALPHA] UGC Anime Face Creator"}]}'
    title = lookup_universe_title("9980885306", fetch_fn=lambda url: body)
    assert title == "[ALPHA] UGC Anime Face Creator"


def test_lookup_returns_none_on_failure():
    def boom(url):
        raise RuntimeError("offline")
    assert lookup_universe_title("123", fetch_fn=boom) is None
