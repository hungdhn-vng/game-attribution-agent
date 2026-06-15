import json
from gaa.server.openclaw_config import render_config

def test_render_wires_maas_provider_and_mcp():
    cfg = json.loads(render_config(model="minimax/minimax-m2.5"))
    prov = cfg["models"]["providers"]["maas"]
    assert prov["api"] == "openai-completions"
    assert prov["baseUrl"] == "${LLM_BASE_URL}" and prov["apiKey"] == "${LLM_API_KEY}"
    assert cfg["agents"]["defaults"]["model"]["primary"] == "maas/minimax/minimax-m2.5"
    assert "gaa" in cfg["agents"]["defaults"]["mcpServers"]

def test_default_model_is_gemma():
    cfg = json.loads(render_config())
    assert cfg["agents"]["defaults"]["model"]["primary"] == "maas/google/gemma-4-31b-it"

def test_mcp_server_invokes_gaa_module():
    cfg = json.loads(render_config())
    gaa = cfg["agents"]["defaults"]["mcpServers"]["gaa"]
    assert gaa["command"] == "python"
    assert gaa["args"] == ["-m", "gaa.mcp.server"]
