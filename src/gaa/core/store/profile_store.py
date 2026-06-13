import sqlite3
from typing import Optional
from gaa.core.schema.profile import GameProfile


class ProfileStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS profiles "
                "(name TEXT PRIMARY KEY, json TEXT NOT NULL)"
            )
            c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, profile: GameProfile) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO profiles(name, json) VALUES(?, ?) "
                "ON CONFLICT(name) DO UPDATE SET json=excluded.json",
                (profile.name, profile.model_dump_json()),
            )

    def get(self, name: str) -> Optional[GameProfile]:
        with self._conn() as c:
            row = c.execute("SELECT json FROM profiles WHERE name=?", (name,)).fetchone()
        return GameProfile.model_validate_json(row[0]) if row else None

    def list_names(self) -> list[str]:
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT name FROM profiles ORDER BY name")]

    def set_active(self, name: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES('active', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (name,),
            )

    def get_active(self) -> Optional[GameProfile]:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        return self.get(row[0]) if row else None
