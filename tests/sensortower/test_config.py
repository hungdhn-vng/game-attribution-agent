from gaa.sensortower import config

def test_defaults_point_at_staging(monkeypatch):
    monkeypatch.delenv("GAA_ST_BASE_URL", raising=False)
    assert config.base_url() == "https://stg-aawp-connector.vnggames.net/sensor-tower-v2"

def test_base_url_override(monkeypatch):
    monkeypatch.setenv("GAA_ST_BASE_URL", "https://example.test/mcp")
    assert config.base_url() == "https://example.test/mcp"

def test_well_known_url_is_host_root_with_resource_suffix(monkeypatch):
    monkeypatch.setenv("GAA_ST_BASE_URL", "https://h.test/sensor-tower-v2")
    assert config.well_known_url() == \
        "https://h.test/.well-known/oauth-authorization-server/sensor-tower-v2"

def test_redirect_uri_from_env(monkeypatch):
    monkeypatch.setenv("GAA_ST_REDIRECT_URI", "https://app.test/api/sensor-tower/callback")
    assert config.redirect_uri() == "https://app.test/api/sensor-tower/callback"
