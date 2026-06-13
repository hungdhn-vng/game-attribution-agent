from gaa.core.crawl.fetcher import CachedFetcher


def test_caches_after_first_fetch(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        return f"body for {url}"

    f = CachedFetcher(cache_dir=str(tmp_path), fetch_fn=fake_fetch)
    assert f.get("http://x") == "body for http://x"
    assert f.get("http://x") == "body for http://x"
    assert calls["n"] == 1  # second call served from cache


def test_falls_back_to_cache_on_fetch_error(tmp_path):
    state = {"fail": False}

    def fake_fetch(url):
        if state["fail"]:
            raise RuntimeError("network down")
        return "live"

    f = CachedFetcher(cache_dir=str(tmp_path), fetch_fn=fake_fetch)
    assert f.get("http://x") == "live"   # populates cache
    state["fail"] = True
    assert f.get("http://x") == "live"   # replays from cache despite error
