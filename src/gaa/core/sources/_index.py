"""Shared helper: index a raw date→value series to 100 at the window start."""


def index_to_100(raw: dict[str, float], start: str, end: str) -> dict[str, float]:
    """Return *raw* filtered to [start, end] and re-indexed so the first kept
    point equals 100.

    Args:
        raw:   Mapping of ISO-date strings to float values.
        start: Inclusive window start (ISO date string, lexicographic compare).
        end:   Inclusive window end   (ISO date string, lexicographic compare).

    Returns:
        Re-indexed dict, or ``{}`` if fewer than 2 points survive the window
        filter, or if the base value is falsy (zero / None).
    """
    kept = {d: v for d, v in raw.items() if start <= d <= end}
    if len(kept) < 2:
        return {}
    base = kept[min(kept)]
    if not base:
        return {}
    return {d: (v / base) * 100.0 for d, v in kept.items()}
