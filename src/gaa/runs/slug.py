from __future__ import annotations

import re
import uuid

_STOPWORDS = {
    "the", "a", "an", "why", "did", "do", "does", "my", "is", "are", "was",
    "were", "what", "s", "to", "of", "in", "on", "for", "last", "this", "week",
    "month", "day", "me", "it", "with", "and", "or", "has", "have",
}


def slugify_query(query: str, max_words: int = 4) -> str:
    """Reduce a free-text query to a short hyphenated topic slug."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    kept = [w for w in words if w not in _STOPWORDS][:max_words]
    return "-".join(kept) if kept else "analysis"


def make_run_id(query: str, today: str, suffix: str | None = None) -> str:
    """Build a human-readable run id: ``YYYY-MM-DD-topic-suffix``.

    ``today`` is an ISO date string (caller passes ``date.today().isoformat()``);
    ``suffix`` defaults to a random 4-char hex so concurrent same-topic runs on
    the same day do not collide.
    """
    sfx = suffix or uuid.uuid4().hex[:4]
    return f"{today}-{slugify_query(query)}-{sfx}"
