"""Shared cited-JSON web-research helper.

answer_fn(prompt) -> {"content": str, "citations": list}. We extract the first
JSON object from the content, attach citations, and degrade to None on any
failure — research feeds are best-effort and must never crash a job.
"""
from __future__ import annotations

from typing import Callable, Optional

from gaa.core.llm.client import _extract_json


def research_json(answer_fn: Callable[[str], dict], prompt: str) -> Optional[dict]:
    try:
        ans = answer_fn(prompt)
        data = _extract_json(ans["content"])
        data["citations"] = ans.get("citations", [])
        return data
    except Exception:
        return None
