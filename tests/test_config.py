from gaa.config import Settings


def test_llm_defaults(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = Settings()
    assert s.llm_base_url.endswith("/v1")
    assert s.db_path.endswith(".sqlite")


def test_llm_env_override(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen-3-27b")
    monkeypatch.setenv("LLM_API_KEY", "k")
    s = Settings()
    assert s.llm_model == "qwen-3-27b" and s.llm_api_key == "k"
