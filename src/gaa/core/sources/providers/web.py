from typing import Callable
from gaa.core.llm.client import _extract_json


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
