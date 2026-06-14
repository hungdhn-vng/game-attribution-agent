"""Read-only BenchmarkSource backed by a BenchmarkStore."""
from __future__ import annotations

from typing import Optional

from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.sources._index import index_to_100


class CrawlingBenchmarkSource:
    """BenchmarkSource that reads quant/qual data from a BenchmarkStore.

    The active platform is set out-of-band via :meth:`set_platform` because
    the ``BenchmarkSource`` protocol's ``genre_trend`` signature only receives
    ``genre``, ``start``, and ``end``.
    """

    def __init__(self, store: BenchmarkStore) -> None:
        self._store = store
        self._platform: str = ""

    def set_platform(self, platform: str) -> None:
        """Set the platform key used for all subsequent store look-ups."""
        self._platform = platform

    def genre_trend(self, genre: str, start: str, end: str) -> dict[str, float]:
        """Return an indexed (100 = window-start) series for *genre*.

        Returns ``{}`` when the platform/genre pair is not cached or when the
        stored payload contains no ``"raw"`` key.
        """
        q = self._store.get_quant(self._platform, genre)
        if q is None or "raw" not in q:
            return {}
        return index_to_100(q["raw"], start, end)

    def qualitative_context(self, genre: str) -> Optional[dict]:
        """Return the stored qualitative payload for *genre*, or ``None``."""
        return self._store.get_qual(self._platform, genre)

    def metric_benchmark(self, metric: str, genre: str):
        """Return the stored per-metric benchmark for the active platform, or None."""
        return self._store.get_benchmark(self._platform, genre, metric)
