"""Durable Sensor Tower state: per-session tokens, pending OAuth states, app client creds.

Lives under GAA_CACHE_DIR/sensortower/state.json (mode 0600) and is added to
persist._durable_items so it snapshots to vStorage. Values are never logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _dir() -> Path:
    d = Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower"
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_path() -> str:
    return str(_dir() / "state.json")


def _read() -> dict:
    try:
        with open(store_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    path = store_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def get_tokens(session: str):
    return _read().get("tokens", {}).get(session)


def set_tokens(session: str, rec: dict) -> None:
    d = _read(); d.setdefault("tokens", {})[session] = rec; _write(d)


def clear_tokens(session: str) -> None:
    d = _read(); d.get("tokens", {}).pop(session, None); _write(d)


def set_pending(state: str, rec: dict) -> None:
    d = _read(); d.setdefault("pending", {})[state] = rec; _write(d)


def pop_pending(state: str):
    d = _read(); rec = d.get("pending", {}).pop(state, None); _write(d); return rec


def get_client():
    return _read().get("client")


def set_client(rec: dict) -> None:
    d = _read(); d["client"] = rec; _write(d)
