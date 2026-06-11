from gaa.llm.client import FakeLLM, LangChainMaaSLLM, _extract_json


def test_fake_llm_returns_preset():
    assert FakeLLM({"main_story": "x"}).complete_json("s", "u")["main_story"] == "x"


def test_extract_json_strips_prose():
    assert _extract_json('Sure: {"a": 1} done')["a"] == 1


def test_maas_client_exposes_complete_json():
    assert hasattr(LangChainMaaSLLM, "complete_json")
