"""Runtime-changeable settings backed by a human-editable TOML file.

Resolution order per key: stored value (TOML) → environment variable → built-in
default — the same contract the old SQLite ConfigStore exposed, so the pipeline's
dynamic sources consume it unchanged. Secrets (e.g. the Perplexity key) are
ENV-ONLY: never written to or read from the file (they live in .env).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tomli_w


@dataclass(frozen=True)
class ConfigKey:
    name: str
    section: str          # TOML section; ignored when env_only
    toml_key: str         # key within the section
    env: str
    default: str = ""
    secret: bool = False
    choices: Optional[tuple] = None
    is_url: bool = False
    env_only: bool = False  # secrets: never file-stored or settable
    max_chars: Optional[int] = None


KEYS: dict = {k.name: k for k in [
    ConfigKey("benchmark_mode", "benchmark", "mode", "GAA_BENCHMARK_MODE",
              default="snapshot", choices=("snapshot", "crawl")),
    ConfigKey("roblox_discover_url_tmpl", "sources", "roblox_discover_url_tmpl",
              "GAA_ROBLOX_DISCOVER_URL_TMPL", is_url=True),
    ConfigKey("roblox_series_url_tmpl", "sources", "roblox_series_url_tmpl",
              "GAA_ROBLOX_SERIES_URL_TMPL", is_url=True),
    ConfigKey("steam_series_url_tmpl", "sources", "steam_series_url_tmpl",
              "GAA_STEAM_SERIES_URL_TMPL", is_url=True),
    ConfigKey("signals_url_tmpl", "sources", "signals_url_tmpl",
              "GAA_SIGNALS_URL_TMPL", is_url=True),
    ConfigKey("behavior_instructions", "behavior", "instructions",
              "GAA_BEHAVIOR_INSTRUCTIONS", max_chars=2000),
    ConfigKey("perplexity_api_key", "", "", "PERPLEXITY_API_KEY",
              secret=True, env_only=True),
]}


class GaaConfig:
    """TOML-backed config with env/default fallback. Drop-in for the old ConfigStore."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        with self._path.open("rb") as f:
            return tomllib.load(f)

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("wb") as f:
            tomli_w.dump(data, f)

    def resolve(self, name: str) -> tuple:
        """Return (value, origin); origin is 'store' | 'env' | 'default'."""
        key = KEYS[name]
        if not key.env_only:
            section = self._read().get(key.section, {})
            if key.toml_key in section:
                return section[key.toml_key], "store"
        env_val = os.environ.get(key.env, "")
        if env_val:
            return env_val, "env"
        return key.default, "default"

    def set(self, name: str, value: Optional[str]) -> None:
        """Set/clear a stored override. None/'' clears it. Secrets are rejected."""
        key = KEYS.get(name)
        if key is None:
            raise KeyError(f"unknown config key: {name!r} (valid: {sorted(KEYS)})")
        if key.env_only:
            raise ValueError(
                f"{name} is a secret — set it in the environment (.env), not the config file")

        data = self._read()
        section = dict(data.get(key.section, {}))

        if value is None or str(value).strip() == "":
            section.pop(key.toml_key, None)
            if section:
                data[key.section] = section
            else:
                data.pop(key.section, None)
            self._write(data)
            return

        value = str(value).strip()
        if key.choices and value not in key.choices:
            raise ValueError(f"{name} must be one of {list(key.choices)}, got {value!r}")
        if key.is_url and not value.startswith(("http://", "https://")):
            raise ValueError(f"{name} must start with http:// or https://")
        if key.max_chars and len(value) > key.max_chars:
            raise ValueError(f"{name} too long ({len(value)} > {key.max_chars} chars)")

        section[key.toml_key] = value
        data[key.section] = section
        self._write(data)

    def all_resolved(self, mask_secrets: bool = True) -> dict:
        out = {}
        for name, key in KEYS.items():
            value, origin = self.resolve(name)
            if mask_secrets and key.secret and value:
                value = "…" + value[-4:]
            out[name] = {"value": value, "origin": origin}
        return out
