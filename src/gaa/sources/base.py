from typing import Protocol


class BenchmarkSource(Protocol):
    def genre_trend(self, genre: str, start: str, end: str) -> dict[str, float]:
        """date(ISO) -> indexed genre metric (100 = window start)."""
        ...


class SignalsSource(Protocol):
    def events(self, game: str, genre: str, start: str, end: str) -> list[dict]:
        """Each: {date, title, kind, url, sentiment}."""
        ...
