"""Persistent cache for per-(platform, genre) benchmark data."""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


class BenchmarkStore:
    """SQLite-backed store for benchmark payloads.

    Table layout::

        benchmark(platform TEXT, genre TEXT, kind TEXT,
                  payload TEXT NOT NULL, fetched_at TEXT,
                  PRIMARY KEY(platform, genre, kind))

    ``kind`` is one of ``"quant"`` or ``"qual"``.
    """

    _CREATE = (
        "CREATE TABLE IF NOT EXISTS benchmark ("
        "platform TEXT NOT NULL, "
        "genre TEXT NOT NULL, "
        "kind TEXT NOT NULL, "
        "payload TEXT NOT NULL, "
        "fetched_at TEXT, "
        "PRIMARY KEY(platform, genre, kind)"
        ")"
    )

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as c:
            c.execute(self._CREATE)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _put(self, platform: str, genre: str, kind: str, payload: dict) -> None:
        fetched_at = self._now_iso()
        with self._conn() as c:
            c.execute(
                "INSERT INTO benchmark(platform, genre, kind, payload, fetched_at) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(platform, genre, kind) DO UPDATE SET "
                "payload=excluded.payload, fetched_at=excluded.fetched_at",
                (platform, genre, kind, json.dumps(payload), fetched_at),
            )

    def _get(self, platform: str, genre: str, kind: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload, fetched_at FROM benchmark "
                "WHERE platform=? AND genre=? AND kind=?",
                (platform, genre, kind),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row[0])
        result["fetched_at"] = row[1]
        return result

    # ── public API ────────────────────────────────────────────────────────────

    def put_quant(
        self,
        platform: str,
        genre: str,
        raw: dict,
        meta: Optional[dict] = None,
    ) -> None:
        """Upsert a quantitative benchmark payload."""
        payload = {**(meta or {}), "raw": raw}
        self._put(platform, genre, "quant", payload)

    def get_quant(self, platform: str, genre: str) -> Optional[dict]:
        """Return the stored quant payload with ``fetched_at`` merged in, or None."""
        return self._get(platform, genre, "quant")

    def put_qual(self, platform: str, genre: str, payload: dict) -> None:
        """Upsert a qualitative benchmark payload."""
        self._put(platform, genre, "qual", payload)

    def get_qual(self, platform: str, genre: str) -> Optional[dict]:
        """Return the stored qual payload with ``fetched_at`` merged in, or None."""
        return self._get(platform, genre, "qual")

    def is_fresh(
        self, platform: str, genre: str, kind: str, ttl_s: float
    ) -> bool:
        """Return True if a row exists and ``now - fetched_at <= ttl_s`` seconds."""
        with self._conn() as c:
            row = c.execute(
                "SELECT fetched_at FROM benchmark "
                "WHERE platform=? AND genre=? AND kind=?",
                (platform, genre, kind),
            ).fetchone()
        if row is None:
            return False
        fetched_at = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        age_s = (now - fetched_at).total_seconds()
        return age_s <= ttl_s
