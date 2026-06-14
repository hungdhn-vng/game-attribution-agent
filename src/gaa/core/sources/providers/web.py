from typing import Callable
from gaa.core.llm.client import _extract_json
from gaa.core.crawl.research import research_json
from gaa.core.analytics.aggregate import RATE_METRICS

_METRIC_LABELS = {
    "retention_d1": "Day 1 retention", "retention_d7": "Day 7 retention",
    "retention_d30": "Day 30 retention", "dau": "daily active users (DAU)",
    "mau": "monthly active users (MAU)", "arppu": "ARPPU", "arpdau": "ARPDAU",
    "revenue": "revenue", "sessions": "sessions per user",
    "playtime": "average session length",
}


class WebSearchBenchmarkProvider:
    """Qualitative benchmark provider backed by Perplexity web-search (sonar model).

    Inject ``answer_fn`` for production use (perplexity_answer) or a fake in tests.
    """

    tier: str = "web"
    produces: str = "qual"

    def __init__(self, answer_fn: Callable[[str], dict]) -> None:
        self._answer_fn = answer_fn

    def qualitative(
        self, genre: str, platform: str, start: str, end: str
    ) -> dict | None:
        """Return a qualitative trend dict or None on failure.

        Returns:
            {"direction": "up"|"down"|"flat", "summary": str, "citations": list}
            or None if the answer cannot be parsed.
        """
        prompt = (
            f"What is the recent popularity and player-count trend of the {genre!r} genre "
            f"on {platform!r} over the period {start} to {end}? "
            'Respond ONLY with a JSON object {"direction": one of up|down|flat, '
            '"summary": one short sentence}.'
        )
        try:
            ans = self._answer_fn(prompt)
            data = _extract_json(ans["content"])
            return {
                "direction": data.get("direction", "flat"),
                "summary": data.get("summary", ""),
                "citations": ans.get("citations", []),
            }
        except Exception:
            return None

    def metric_benchmark(self, metric, genre, platform, start, end):
        """Return a cited benchmark range for `metric` in genre+platform, or None.

        Shape: {metric, low, high, median|None, unit, source, confidence,
        citations, summary}. Rate metrics are normalized to fractions.
        """
        label = _METRIC_LABELS.get(metric, metric)
        prompt = (
            f"What is the typical benchmark RANGE for {label} of {genre!r} games on "
            f"{platform!r} as of {start} to {end}? Prefer the 50th-90th percentile range. "
            'Respond ONLY with a JSON object {"low": number, "high": number, '
            '"median": number or null, "unit": "percent"|"fraction"|"raw", '
            '"source": short string, "confidence": "high"|"med"|"low", '
            '"summary": one short sentence}.'
        )
        data = research_json(self._answer_fn, prompt)
        if not data:
            return None
        try:
            low, high = float(data["low"]), float(data["high"])
        except (KeyError, TypeError, ValueError):
            return None
        median = data.get("median")
        try:
            median = float(median) if median not in (None, "") else None
        except (TypeError, ValueError):
            median = None
        is_rate = metric in RATE_METRICS
        if data.get("unit") == "percent" and is_rate:
            low, high = low / 100.0, high / 100.0
            median = median / 100.0 if median is not None else None
        return {
            "metric": metric, "low": low, "high": high, "median": median,
            "unit": "fraction" if is_rate else (data.get("unit") or "raw"),
            "source": data.get("source", ""), "confidence": data.get("confidence", "low"),
            "citations": data.get("citations", []), "summary": data.get("summary", ""),
        }
