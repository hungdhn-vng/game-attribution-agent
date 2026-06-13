import pytest

from gaa.config import GaaConfig, KEYS


def _cfg(tmp_path):
    return GaaConfig(str(tmp_path / "gaa-config.toml"))


def test_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("GAA_BENCHMARK_MODE", raising=False)
    assert _cfg(tmp_path).resolve("benchmark_mode") == ("snapshot", "default")


def test_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    assert _cfg(tmp_path).resolve("benchmark_mode") == ("crawl", "env")


def test_stored_value_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_BENCHMARK_MODE", "crawl")
    cfg = _cfg(tmp_path)
    cfg.set("benchmark_mode", "snapshot")
    assert cfg.resolve("benchmark_mode") == ("snapshot", "store")
    assert _cfg(tmp_path).resolve("benchmark_mode") == ("snapshot", "store")


def test_set_writes_sectioned_toml(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.set("benchmark_mode", "crawl")
    cfg.set("steam_series_url_tmpl", "https://example.com/{app}.json")
    text = (tmp_path / "gaa-config.toml").read_text()
    assert "[benchmark]" in text and "mode" in text
    assert "[sources]" in text and "steam_series_url_tmpl" in text


def test_clear_removes_key(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.set("benchmark_mode", "crawl")
    cfg.set("benchmark_mode", "")
    assert cfg.resolve("benchmark_mode") == ("snapshot", "default")


def test_enum_validation(tmp_path):
    with pytest.raises(ValueError):
        _cfg(tmp_path).set("benchmark_mode", "bogus")


def test_url_validation(tmp_path):
    with pytest.raises(ValueError):
        _cfg(tmp_path).set("steam_series_url_tmpl", "not-a-url")


def test_behavior_length_cap(tmp_path):
    with pytest.raises(ValueError):
        _cfg(tmp_path).set("behavior_instructions", "x" * 2001)


def test_secret_is_env_only(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        cfg.set("perplexity_api_key", "pplx-123")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-secret")
    assert cfg.resolve("perplexity_api_key") == ("pplx-secret", "env")


def test_all_resolved_masks_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-abcd1234")
    out = _cfg(tmp_path).all_resolved()
    assert set(out) == set(KEYS)
    assert out["perplexity_api_key"]["value"].endswith("1234")
    assert out["perplexity_api_key"]["value"].startswith("…")


def test_unknown_key_raises(tmp_path):
    with pytest.raises(KeyError):
        _cfg(tmp_path).resolve("nope")
