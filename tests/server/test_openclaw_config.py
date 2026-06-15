import json
from gaa.server.openclaw_config import render_config


def test_render_wires_maas_provider_and_mcp():
    cfg = json.loads(render_config(model="minimax/minimax-m2.5"))
    prov = cfg["models"]["providers"]["maas"]
    assert prov["api"] == "openai-completions"
    assert prov["baseUrl"] == "${LLM_BASE_URL}" and prov["apiKey"] == "${LLM_API_KEY}"
    assert cfg["models"]["mode"] == "merge"
    assert cfg["agents"]["defaults"]["model"]["primary"] == "maas/minimax/minimax-m2.5"
    assert "mcpServers" not in cfg["agents"]["defaults"]


def test_default_model_is_gemma():
    cfg = json.loads(render_config())
    assert cfg["agents"]["defaults"]["model"]["primary"] == "maas/google/gemma-4-31b-it"


def test_mcp_top_level_servers():
    cfg = json.loads(render_config())
    gaa = cfg["mcp"]["servers"]["gaa"]
    assert gaa["command"] == "python3"
    assert gaa["args"] == ["-m", "gaa.mcp.server"]
    assert "env" not in gaa


def test_gateway_http_endpoints():
    cfg = json.loads(render_config())
    endpoints = cfg["gateway"]["http"]["endpoints"]
    assert endpoints["chatCompletions"]["enabled"] is True
    assert endpoints["responses"]["enabled"] is True


def test_gateway_auth():
    cfg = json.loads(render_config())
    auth = cfg["gateway"]["auth"]
    assert auth["mode"] == "token"
    assert auth["token"] == "${OPENCLAW_GATEWAY_TOKEN}"
