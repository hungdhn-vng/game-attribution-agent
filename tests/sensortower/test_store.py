import os, stat
from gaa.sensortower import store

def _dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))

def test_token_round_trip(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_tokens("default", {"access_token": "a", "refresh_token": "r", "expiry": 123.0})
    assert store.get_tokens("default")["access_token"] == "a"
    assert store.get_tokens("missing") is None

def test_clear_tokens(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_tokens("s", {"access_token": "a", "refresh_token": "r", "expiry": 1.0})
    store.clear_tokens("s")
    assert store.get_tokens("s") is None

def test_clear_tokens_noop_when_no_store(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.clear_tokens("nonexistent")  # must not raise on an empty/absent store
    assert store.get_tokens("nonexistent") is None

def test_store_path_has_no_side_effects(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    p = store.store_path()
    assert not os.path.exists(os.path.dirname(p))  # querying the path must not create the dir

def test_pending_round_trip_and_pop_is_single_use(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_pending("st8", {"code_verifier": "v", "session": "default", "ts": 100.0})
    rec = store.pop_pending("st8")
    assert rec["code_verifier"] == "v"
    assert store.pop_pending("st8") is None

def test_client_creds_round_trip(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    assert store.get_client() is None
    store.set_client({"client_id": "c", "client_secret": "s", "expires_at": 0.0})
    assert store.get_client()["client_id"] == "c"

def test_file_is_0600(tmp_path, monkeypatch):
    _dir(tmp_path, monkeypatch)
    store.set_tokens("s", {"access_token": "a", "refresh_token": "r", "expiry": 1.0})
    mode = stat.S_IMODE(os.stat(store.store_path()).st_mode)
    assert mode == 0o600
