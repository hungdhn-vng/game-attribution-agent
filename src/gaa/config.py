import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass
class Settings:
    llm_base_url: str = field(default_factory=lambda: _env(
        "LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL"))
    memory_id: str = field(default_factory=lambda: _env("MEMORY_ID"))
    db_path: str = field(default_factory=lambda: _env("GAA_DB_PATH", "gaa.sqlite"))
    cache_dir: str = field(default_factory=lambda: _env("GAA_CACHE_DIR", "data/cache"))
    perplexity_api_key: str = field(default_factory=lambda: _env("PERPLEXITY_API_KEY", ""))
    perplexity_base_url: str = field(default_factory=lambda: _env("PERPLEXITY_BASE_URL", "https://api.perplexity.ai"))
    perplexity_model: str = field(default_factory=lambda: _env("PERPLEXITY_MODEL", "sonar"))
