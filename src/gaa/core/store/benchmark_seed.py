"""Seed a BenchmarkStore from a static snapshot JSON file.

The snapshot file maps ``"platform/genre"`` keys to objects with a ``"raw"``
series and an optional ``"tier"`` string.  Seeding is idempotent: any
``(platform, genre)`` pair that already has a quant entry in the store is
skipped so live-crawled data is never overwritten by the seed.
"""
from __future__ import annotations

import json
import os

from gaa.core.store.benchmark_store import BenchmarkStore


def seed_benchmark_store(store: BenchmarkStore, snapshot_path: str) -> int:
    """Load *snapshot_path* and seed missing ``(platform, genre)`` quant entries.

    Parameters
    ----------
    store:
        A ``BenchmarkStore`` instance to seed.
    snapshot_path:
        Path to a JSON file mapping ``"platform/genre"`` →
        ``{"raw": {iso_date: value, ...}, "tier": str}``.

    Returns
    -------
    int
        Number of entries actually written (0 if the file is missing or all
        entries already exist in the store).
    """
    if not os.path.isfile(snapshot_path):
        return 0

    try:
        with open(snapshot_path, "r", encoding="utf-8") as fh:
            snapshot: dict = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return 0

    seeded = 0
    for key, entry in snapshot.items():
        if "/" not in key:
            continue
        platform, genre = key.split("/", 1)
        if store.get_quant(platform, genre) is not None:
            continue  # already present — do not overwrite
        raw = entry.get("raw")
        if not isinstance(raw, dict) or not raw:
            continue
        meta = {"tier": entry.get("tier", "snapshot")}
        store.put_quant(platform, genre, raw=raw, meta=meta)
        seeded += 1

    return seeded
