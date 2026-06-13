"""Runtime-changeable settings with env-var fallback (spec: OpenClaw chat integration).

Resolution order per key: stored value -> environment variable -> built-in default.
Stores live in the same SQLite file as ProfileStore (separate `config` table), so
admin changes survive restarts but env vars still work as deploy-time defaults.
"""
import os
import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ConfigKey:
    name: str
    env: str
    default: str = ""
    secret: bool = False
    choices: Optional[tuple] = None
    is_url: bool = False


KEYS: dict = {k.name: k for k in [
    ConfigKey("benchmark_mode", "GAA_BENCHMARK_MODE",
              default="snapshot", choices=("snapshot", "crawl")),
    ConfigKey("roblox_discover_url_tmpl", "GAA_ROBLOX_DISCOVER_URL_TMPL", is_url=True),
    ConfigKey("roblox_series_url_tmpl", "GAA_ROBLOX_SERIES_URL_TMPL", is_url=True),
    ConfigKey("steam_series_url_tmpl", "GAA_STEAM_SERIES_URL_TMPL", is_url=True),
    ConfigKey("perplexity_api_key", "PERPLEXITY_API_KEY", secret=True),
    ConfigKey("signals_url_tmpl", "GAA_SIGNALS_URL_TMPL", is_url=True),
    ConfigKey("behavior_instructions", "GAA_BEHAVIOR_INSTRUCTIONS"),
]}


class ConfigStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS config "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def resolve(self, name: str) -> tuple:
        """Return (value, origin); origin is 'store' | 'env' | 'default'."""
        key = KEYS[name]  # KeyError on unknown key is intentional
        with self._conn() as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (name,)).fetchone()
        if row is not None:
            return row[0], "store"
        env_val = os.environ.get(key.env, "")
        if env_val:
            return env_val, "env"
        return key.default, "default"

    def set(self, name: str, value: Optional[str]) -> None:
        """Set a stored override; None or '' clears it (falling back to env/default)."""
        key = KEYS.get(name)
        if key is None:
            raise KeyError(f"unknown config key: {name!r} (valid: {sorted(KEYS)})")
        if value is None or str(value).strip() == "":
            with self._conn() as c:
                c.execute("DELETE FROM config WHERE key=?", (name,))
            return
        value = str(value).strip()
        if key.choices and value not in key.choices:
            raise ValueError(f"{name} must be one of {list(key.choices)}, got {value!r}")
        if key.is_url and not value.startswith(("http://", "https://")):
            raise ValueError(f"{name} must start with http:// or https://")
        with self._conn() as c:
            c.execute(
                "INSERT INTO config(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (name, value),
            )

    def all_resolved(self, mask_secrets: bool = True) -> dict:
        out = {}
        for name, key in KEYS.items():
            value, origin = self.resolve(name)
            if mask_secrets and key.secret and value:
                value = "…" + value[-4:]
            out[name] = {"value": value, "origin": origin}
        return out
