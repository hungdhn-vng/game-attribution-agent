class FixtureBenchmarkSource:
    def __init__(self, genre_index: dict | None = None) -> None:
        self._idx = genre_index or {}

    def genre_trend(self, genre: str, start: str, end: str) -> dict:
        return {d: v for d, v in self._idx.items() if start <= d <= end}


class FixtureSignalsSource:
    def __init__(self, events: list | None = None) -> None:
        self._events = events or []

    def events(self, game: str, genre: str, start: str, end: str) -> list:
        return [e for e in self._events if start <= e["date"] <= end]
