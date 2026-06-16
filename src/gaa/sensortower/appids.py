"""Per-profile Sensor Tower app-ID map, stored in its own table inside the profiles
sqlite (snapshotted via the profiles.sqlite arcname). Keeps GameProfile untouched."""
from __future__ import annotations

import sqlite3


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.execute(
        "CREATE TABLE IF NOT EXISTS st_app_ids "
        "(profile TEXT, label TEXT, id TEXT NOT NULL, id_type TEXT NOT NULL, "
        " PRIMARY KEY (profile, label))"
    )
    return c


def set_app_id(db_path: str, profile: str, label: str, id, id_type: str = "app_id") -> None:
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO st_app_ids(profile,label,id,id_type) VALUES(?,?,?,?) "
            "ON CONFLICT(profile,label) DO UPDATE SET id=excluded.id, id_type=excluded.id_type",
            (profile, label, str(id), id_type),
        )


def _coerce(id_str: str):
    try:
        return int(id_str)
    except (TypeError, ValueError):
        return id_str


def get_app_ids(db_path: str, profile: str) -> dict:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT label,id,id_type FROM st_app_ids WHERE profile=?", (profile,)
        ).fetchall()
    return {lbl: {"id": _coerce(i), "id_type": t} for lbl, i, t in rows}


def resolve(db_path: str, profile: str, label: str):
    return get_app_ids(db_path, profile).get(label)
