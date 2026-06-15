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
    # OpenClaw's env-var security filter strips GAA_*/LLM_* from the MCP subprocess,
    # so they are re-injected here as ${ENV} refs (substituted at config load — verified
    # live in the Phase A/E spike that mcp.servers.*.env DOES do ${VAR} substitution).
    assert gaa["env"]["LLM_API_KEY"] == "${LLM_API_KEY}"
    assert gaa["env"]["GAA_RUN_SIDECAR"] == "${GAA_RUN_SIDECAR}"
    assert gaa["env"]["GAA_DB_PATH"] == "${GAA_DB_PATH}"
    # vStorage creds must be forwarded so the MCP subprocess can snapshot on mutation
    assert gaa["env"]["VSTORAGE_ENDPOINT"] == "${VSTORAGE_ENDPOINT}"
    assert gaa["env"]["VSTORAGE_BUCKET"] == "${VSTORAGE_BUCKET}"
    assert gaa["env"]["VSTORAGE_ACCESS_KEY"] == "${VSTORAGE_ACCESS_KEY}"
    assert gaa["env"]["VSTORAGE_SECRET_KEY"] == "${VSTORAGE_SECRET_KEY}"
    assert gaa["env"]["VSTORAGE_REGION"] == "${VSTORAGE_REGION}"


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
