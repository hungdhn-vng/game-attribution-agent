import httpx
from gaa.core.settings import Settings


def perplexity_answer(prompt: str, settings: Settings | None = None) -> dict:
    """POST a prompt to Perplexity's chat completions endpoint and return content + citations."""
    s = settings or Settings()
    resp = httpx.post(
        f"{s.perplexity_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {s.perplexity_api_key}"},
        json={
            "model": s.perplexity_model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=25.0,
    )
    resp.raise_for_status()
    data = resp.json()
    # The live API returns citations as plain URL strings; normalize to dicts.
    citations = [c if isinstance(c, dict) else {"url": c}
                 for c in data.get("citations", [])]
    return {
        "content": data["choices"][0]["message"]["content"],
        "citations": citations,
    }
