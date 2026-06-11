from typing import Protocol, runtime_checkable


@runtime_checkable
class BenchmarkProvider(Protocol):
    """Protocol for benchmark data providers.

    Class attributes:
        tier: identifies the data source (e.g. "roblox", "steam").
        produces: data type produced — "quant" (quantitative) or "qual" (qualitative).
    """
    tier: str
    produces: str

    def discover(self, genre: str) -> list[str]:
        """Return a list of comparator identifiers for the given genre."""
        ...

    def series_for(self, comparator: str) -> dict[str, float]:
        """Return a time-series {date: value} for the given comparator id."""
        ...
