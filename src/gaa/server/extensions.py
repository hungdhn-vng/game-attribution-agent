"""Durable registry of admin-registered MCP servers + a secret store.

Both files live under GAA_CACHE_DIR so persist._durable_items snapshots them to
vStorage. Secrets file is mode 0600 and its values are never listed/logged.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def _dir() -> Path:
    d = Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "extensions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> str:
    return str(_dir() / "mcp_registry.json")


def secrets_path() -> str:
    return str(_dir() / "mcp_secrets.json")


def _read(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def list_servers() -> list[dict]:
    return _read(registry_path(), [])


def add_server(*, name: str, command, args, url, env) -> dict:
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"invalid server name: {name!r} (use [a-z0-9_], <=32)")
    if name == "gaa":
        raise ValueError("'gaa' is a reserved server name")
    if not command and not url:
        raise ValueError("server needs a command or a url")
    servers = [s for s in list_servers() if s["name"] != name]
    entry = {"name": name, "command": command, "args": list(args or []),
             "url": url, "env": dict(env or {})}
    servers.append(entry)
    with open(registry_path(), "w") as f:
        json.dump(servers, f, indent=2)
    return entry


def remove_server(name: str) -> bool:
    servers = list_servers()
    kept = [s for s in servers if s["name"] != name]
    with open(registry_path(), "w") as f:
        json.dump(kept, f, indent=2)
    return len(kept) != len(servers)


def _read_secrets() -> dict:
    return _read(secrets_path(), {})


def _write_secrets(d: dict) -> None:
    path = secrets_path()
    with open(path, "w") as f:
        json.dump(d, f)
    os.chmod(path, 0o600)


def set_secret(name: str, value: str) -> None:
    if not _NAME_RE.match((name or "").lower()):
        raise ValueError(f"invalid secret name: {name!r}")
    d = _read_secrets(); d[name] = value; _write_secrets(d)


def unset_secret(name: str) -> bool:
    d = _read_secrets()
    existed = name in d
    d.pop(name, None); _write_secrets(d)
    return existed


def get_secret(name: str):
    return _read_secrets().get(name)


def list_secret_names() -> list[str]:
    return sorted(_read_secrets().keys())


def reload_flag_path() -> str:
    return str(_dir() / "reload.flag")


def request_reload() -> None:
    """Signal the supervisor to re-render configs and reload the gateways."""
    with open(reload_flag_path(), "w") as f:
        f.write("1")
