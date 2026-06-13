import json
import os


class SeededBenchmarkSource:
    """BenchmarkSource backed by a bundled static genre-trend JSON (the spec's 'seeded
    benchmark' layer). Used as a demo-safe fallback when no live endpoint is configured."""
    def __init__(self, seed_path: str) -> None:
        self._data = json.load(open(seed_path, encoding="utf-8")) if os.path.exists(seed_path) else {}

    def genre_trend(self, genre: str, start: str, end: str) -> dict:
        series = self._data.get(genre) or self._data.get("_default") or {}
        raw = {d: float(v) for d, v in series.items() if start <= d <= end}
        if len(raw) < 2:
            return {}
        base = raw[min(raw)]
        return {d: (v / base) * 100.0 for d, v in raw.items()} if base else {}
