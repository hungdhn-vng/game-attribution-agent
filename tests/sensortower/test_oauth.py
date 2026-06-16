import httpx
import pytest
from gaa.sensortower import oauth, store, config

DISC = {
    "authorization_endpoint": "https://h.test/sensor-tower-v2/authorize",
    "token_endpoint": "https://h.test/sensor-tower-v2/token",
    "registration_endpoint": "https://h.test/sensor-tower-v2/register",
}

@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_ST_BASE_URL", "https://h.test/sensor-tower-v2")
    monkeypatch.setenv("GAA_ST_REDIRECT_URI", "https://app.test/api/sensor-tower/callback")
    oauth._ENDPOINTS_CACHE.clear()

def _mount(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def factory(*a, **k):
        k["transport"] = transport
        return real_client(*a, **k)
    monkeypatch.setattr(oauth.httpx, "Client", factory)

def test_ensure_client_registers_once(monkeypatch):
    calls = {"register": 0}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/oauth-authorization-server/sensor-tower-v2"):
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            calls["register"] += 1
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    c1 = oauth.ensure_client(); c2 = oauth.ensure_client()
    assert c1["client_id"] == "cid" and calls["register"] == 1

def test_authorize_url_has_pkce_and_state(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    url = oauth.build_authorize_url("default", now=1000.0)
    assert url.startswith("https://h.test/sensor-tower-v2/authorize?")
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "state=" in url and "client_id=cid" in url
    import urllib.parse as up
    state = up.parse_qs(up.urlparse(url).query)["state"][0]
    assert store.pop_pending(state)["session"] == "default"

def test_exchange_code_stores_tokens(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    url = oauth.build_authorize_url("default", now=1000.0)
    import urllib.parse as up
    state = up.parse_qs(up.urlparse(url).query)["state"][0]
    rec = oauth.exchange_code("CODE", state, now=1000.0)
    assert rec["access_token"] == "AT"
    assert store.get_tokens("default")["expiry"] == 1000.0 + 3600 - 60

def test_exchange_code_rejects_expired_pending(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"client_id": "cid", "client_secret": "sec"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    url = oauth.build_authorize_url("default", now=1000.0)
    import urllib.parse as up
    state = up.parse_qs(up.urlparse(url).query)["state"][0]
    with pytest.raises(ValueError):  # 601s later → past the 600s TTL
        oauth.exchange_code("CODE", state, now=1000.0 + 601)

def test_exchange_code_rejects_unknown_state(monkeypatch):
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    with pytest.raises(ValueError):
        oauth.exchange_code("CODE", "bogus", now=1.0)

def test_valid_access_token_refreshes_when_expired(monkeypatch):
    store.set_client({"client_id": "cid", "client_secret": "sec", "expires_at": 0.0})
    store.set_tokens("default", {"access_token": "OLD", "refresh_token": "RT", "expiry": 500.0})
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    tok = oauth.valid_access_token("default", now=1000.0)
    assert tok == "NEW"
    assert store.get_tokens("default")["refresh_token"] == "RT2"

def test_valid_access_token_none_when_refresh_fails(monkeypatch):
    store.set_client({"client_id": "cid", "client_secret": "sec", "expires_at": 0.0})
    store.set_tokens("default", {"access_token": "OLD", "refresh_token": "RT", "expiry": 1.0})
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/token"):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    assert oauth.valid_access_token("default", now=1000.0) is None
    assert store.get_tokens("default") is None


def test_valid_access_token_returns_cached_when_not_expired(monkeypatch):
    # Fast path: a still-valid token must be returned with NO network call (no _mount).
    store.set_tokens("default", {"access_token": "LIVE", "refresh_token": "RT", "expiry": 9000.0})
    assert oauth.valid_access_token("default", now=1000.0) == "LIVE"


def test_valid_access_token_keeps_token_on_transient_error(monkeypatch):
    # A network blip during refresh must NOT clear a still-valid refresh token.
    store.set_client({"client_id": "cid", "client_secret": "sec", "expires_at": 0.0})
    store.set_tokens("default", {"access_token": "OLD", "refresh_token": "RT", "expiry": 1.0})
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/token"):
            raise httpx.ConnectError("boom")
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    assert oauth.valid_access_token("default", now=1000.0) is None
    assert store.get_tokens("default")["refresh_token"] == "RT"  # preserved for retry


def test_valid_access_token_keeps_token_on_5xx(monkeypatch):
    # A 5xx from the token endpoint is transient, not a dead token → keep it.
    store.set_client({"client_id": "cid", "client_secret": "sec", "expires_at": 0.0})
    store.set_tokens("default", {"access_token": "OLD", "refresh_token": "RT", "expiry": 1.0})
    def handler(req):
        if "oauth-authorization-server" in req.url.path:
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/token"):
            return httpx.Response(503, json={"error": "temporarily_unavailable"})
        return httpx.Response(404)
    _mount(monkeypatch, handler)
    assert oauth.valid_access_token("default", now=1000.0) is None
    assert store.get_tokens("default")["refresh_token"] == "RT"  # preserved for retry
