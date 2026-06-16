"""Global, query-keyed Sensor Tower result cache. One JSON file under GAA_CACHE_DIR,
added to persist._durable_items → snapshotted to vStorage (cross-session/restart).
A hit short-circuits the browser relay (no data points spent)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

_MAX_ENTRIES = 500
_TTL_DEFAULT = 7 * 86400
_TTL_RECENT = 86400
_RECENT_WINDOW_DAYS = 3


def store_path() -> str:
    return str(Path(os.environ.get("GAA_CACHE_DIR", "data/cache")) / "sensortower" / "st_cache.json")


def _dir() -> Path:
    d = Path(store_path()).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_key(built: dict) -> str:
    def norm(v):
        if isinstance(v, list):
            return sorted(norm(x) for x in v)
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v)}
        return v
    payload = json.dumps(
        {"st_tool": built["st_tool"], "params": norm(built.get("params", {}))},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _read() -> dict:
    try:
        with open(store_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    _dir()
    path = store_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)


def _utc_date(ts: float) -> date:
    """Convert a Unix timestamp to a UTC date. Uses timezone-aware arithmetic to
    avoid local-tz surprises when the timestamp is near midnight UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


def _ttl_for(end_date: str, now: float) -> int:
    try:
        ed = date.fromisoformat(end_date)
        now_d = _utc_date(now)
        delta = (now_d - ed).days
        if 0 <= delta <= _RECENT_WINDOW_DAYS:
            return _TTL_RECENT
    except (TypeError, ValueError):
        pass
    return _TTL_DEFAULT


def get(key: str, *, now: float):
    d = _read()
    e = d.get(key)
    if not e:
        return None
    if now - e["ts"] >= _ttl_for(e.get("end_date", ""), now):
        return None
    e["last"] = now
    _write(d)
    return e["data"]


def put(key: str, data, *, end_date: str, now: float) -> None:
    d = _read()
    d[key] = {"data": data, "end_date": end_date, "ts": now, "last": now}
    if len(d) > _MAX_ENTRIES:
        for k in sorted(d, key=lambda k: d[k]["last"])[: len(d) - _MAX_ENTRIES]:
            del d[k]
    _write(d)
