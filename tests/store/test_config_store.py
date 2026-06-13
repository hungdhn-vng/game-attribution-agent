import pytest

from gaa.core.store.config_store import ConfigStore, KEYS


@pytest.fixture
def store(tmp_path):
    return ConfigStore(str(tmp_path / "config.sqlite"))


def test_default_when_nothing_set(store, monkeypatch):
    monkeypatch.delenv("GAA_BENCHMARK_MODE", raising=False)
    assert store.resolve("benchmark_mode") == ("snapshot", "default")


def test_env_beats_default(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    assert store.resolve("benchmark_mode") == ("crawl", "env")


def test_empty_env_falls_through_to_default(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "")
    assert store.resolve("benchmark_mode") == ("snapshot", "default")


def test_store_beats_env(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "snapshot")
    store.set("benchmark_mode", "crawl")
    assert store.resolve("benchmark_mode") == ("crawl", "store")


def test_clear_restores_env(store, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    store.set("benchmark_mode", "snapshot")
    store.set("benchmark_mode", None)
    assert store.resolve("benchmark_mode") == ("crawl", "env")


def test_choices_validated(store):
    with pytest.raises(ValueError):
        store.set("benchmark_mode", "banana")


def test_url_keys_validated(store):
    with pytest.raises(ValueError):
        store.set("signals_url_tmpl", "not-a-url")
    store.set("signals_url_tmpl", "https://example.com/q={q}")
    assert store.resolve("signals_url_tmpl") == ("https://example.com/q={q}", "store")


def test_unknown_key_rejected(store):
    with pytest.raises(KeyError):
        store.set("nope", "x")
    with pytest.raises(KeyError):
        store.resolve("nope")


def test_all_resolved_masks_secrets(store, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    store.set("perplexity_api_key", "pplx-abcdef123456")
    out = store.all_resolved()
    assert set(out) == set(KEYS)
    assert out["perplexity_api_key"]["value"] == "…3456"
    assert out["perplexity_api_key"]["origin"] == "store"


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "config.sqlite")
    ConfigStore(path).set("benchmark_mode", "crawl")
    assert ConfigStore(path).resolve("benchmark_mode") == ("crawl", "store")
