from gaa.sensortower import cache

def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "c"))

def test_key_normalizes_equivalent_queries():
    a = {"st_tool": "x", "params": {"app_id": [2, 1], "countries": ["US", "VN"], "bundles": ["b"]}}
    b = {"st_tool": "x", "params": {"bundles": ["b"], "countries": ["VN", "US"], "app_id": [1, 2]}}
    assert cache.make_key(a) == cache.make_key(b)

def test_key_stable_with_mixed_app_id_types():
    a = {"st_tool": "x", "params": {"app_id": [123, "com.example.app"]}}
    b = {"st_tool": "x", "params": {"app_id": ["com.example.app", 123]}}
    assert cache.make_key(a) == cache.make_key(b)  # mixed int/str must not crash

def test_put_get_hit(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    cache.put("k", {"v": 1}, end_date="2024-01-01", now=1000.0)
    assert cache.get("k", now=1000.0) == {"v": 1}

def test_miss_returns_none(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert cache.get("nope", now=1000.0) is None

def test_ttl_historical_7d(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    cache.put("k", {"v": 1}, end_date="2020-01-01", now=0.0)
    assert cache.get("k", now=6 * 86400) == {"v": 1}
    assert cache.get("k", now=8 * 86400) is None

def test_ttl_recent_24h(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    cache.put("k", {"v": 1}, end_date="1970-01-02", now=86400.0)
    assert cache.get("k", now=86400.0 + 23 * 3600) == {"v": 1}
    assert cache.get("k", now=86400.0 + 25 * 3600) is None

def test_lru_eviction(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    monkeypatch.setattr(cache, "_MAX_ENTRIES", 2)
    cache.put("a", {}, end_date="2020-01-01", now=1.0)
    cache.put("b", {}, end_date="2020-01-01", now=2.0)
    cache.get("a", now=3.0)
    cache.put("c", {}, end_date="2020-01-01", now=4.0)
    assert cache.get("b", now=5.0) is None
    assert cache.get("a", now=5.0) == {}
