import pytest

import gaa.core.sources.dynamic as dyn
from gaa.core.settings import Settings
from gaa.config import GaaConfig


class StubRefresher:
    last_kwargs = None

    def __init__(self, store, providers_by_platform, web_provider):
        StubRefresher.last_kwargs = {
            "store": store,
            "providers_by_platform": providers_by_platform,
            "web_provider": web_provider,
        }

    def refresh(self, platform, genre, start=None, end=None, deadline=None):
        return {"status": "ok", "platform": platform}


class StubSignals:
    def __init__(self, *a, **kw):
        self.kw = kw

    def events(self, game, genre, start, end):
        return [{"src": "web"}]


class StubFixture:
    def __init__(self, items):
        self.items = items

    def events(self, game, genre, start, end):
        return []


@pytest.fixture
def config(tmp_path, monkeypatch):
    for var in ("GAA_BENCHMARK_MODE", "GAA_ROBLOX_DISCOVER_URL_TMPL",
                "GAA_ROBLOX_SERIES_URL_TMPL", "GAA_STEAM_SERIES_URL_TMPL",
                "PERPLEXITY_API_KEY", "GAA_SIGNALS_URL_TMPL"):
        monkeypatch.delenv(var, raising=False)
    return GaaConfig(str(tmp_path / "gaa-config.toml"))


@pytest.fixture
def settings(tmp_path):
    return Settings(cache_dir=str(tmp_path / "cache"))


def test_snapshot_mode_builds_empty_providers(config, settings, monkeypatch):
    monkeypatch.setattr(dyn, "BenchmarkRefresher", StubRefresher)
    r = dyn.DynamicRefresher(config=config, settings=settings, store="STORE")
    out = r.refresh("roblox", "survival", "2026-01-01", "2026-01-31")
    assert out["status"] == "ok"
    assert StubRefresher.last_kwargs["providers_by_platform"] == {}
    assert StubRefresher.last_kwargs["web_provider"] is None


def test_crawl_mode_builds_providers_from_current_config(config, settings, monkeypatch):
    monkeypatch.setattr(dyn, "BenchmarkRefresher", StubRefresher)
    r = dyn.DynamicRefresher(config=config, settings=settings, store="STORE")
    # flip config AFTER constructing the facade — must take effect on next call
    config.set("benchmark_mode", "crawl")
    # perplexity_api_key is env-only in GaaConfig; set via env var instead
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
    r.refresh("steam", "survival")
    kw = StubRefresher.last_kwargs
    assert set(kw["providers_by_platform"]) == {"roblox", "steam"}
    assert kw["web_provider"] is not None


def test_dynamic_signals_switches_on_config(config, settings, monkeypatch):
    monkeypatch.setattr(dyn, "WebSignalsSource", StubSignals)
    monkeypatch.setattr(dyn, "FixtureSignalsSource", StubFixture)
    s = dyn.DynamicSignals(config=config, settings=settings)
    assert s.events("g", "survival", "2026-01-01", "2026-01-31") == []
    config.set("signals_url_tmpl", "https://example.com/news?q={q}")
    assert s.events("g", "survival", "2026-01-01", "2026-01-31") == [{"src": "web"}]
