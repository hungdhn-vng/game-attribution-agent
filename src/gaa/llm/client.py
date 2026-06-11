import json
from typing import Optional, Protocol
from gaa.config import Settings


class LLM(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class FakeLLM:
    """Test double: returns a preset dict regardless of input."""
    def __init__(self, preset: dict) -> None:
        self._preset = preset

    def complete_json(self, system: str, user: str) -> dict:
        return dict(self._preset)


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start:end + 1])


class LangChainMaaSLLM:
    """OpenAI-compatible client against GreenNode AI Platform (MaaS) via langchain-openai."""
    def __init__(self, settings: Optional[Settings] = None) -> None:
        import os
        from langchain_openai import ChatOpenAI
        s = settings or Settings()
        self._llm = ChatOpenAI(model=s.llm_model, base_url=s.llm_base_url,
                               api_key=s.llm_api_key, temperature=0,
                               max_tokens=int(os.environ.get("GAA_MAX_TOKENS", "1024")))

    def complete_json(self, system: str, user: str) -> dict:
        from langchain_core.messages import SystemMessage, HumanMessage
        resp = self._llm.invoke([
            SystemMessage(content=system + "\nRespond ONLY with one valid JSON object."),
            HumanMessage(content=user),
        ])
        return _extract_json(resp.content)
