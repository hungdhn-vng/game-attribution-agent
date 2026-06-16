import json
from gaa.server.openclaw_config import render_config


def test_nonadmin_allowlists_gaa_and_omits_deny():
    cfg = json.loads(render_config(profile="nonadmin"))
    assert "deny" not in cfg.get("tools", {})           # the ineffective blocklist is gone
    assert cfg["tools"]["allow"] == ["gaa__*"]           # verified absolute allowlist (Spike A)
    assert cfg["mcp"]["servers"]["gaa"]["env"]["GAA_MCP_ADMIN"] == "0"
    assert cfg["agents"]["defaults"]["workspace"]         # shared persona workspace (Spike C)


def test_admin_omits_tools_key_and_admin_mcp():
    cfg = json.loads(render_config(profile="admin"))
    assert "tools" not in cfg                             # omitting tools = full built-in suite
    assert cfg["mcp"]["servers"]["gaa"]["env"]["GAA_MCP_ADMIN"] == "1"


def test_default_profile_is_nonadmin():
    assert json.loads(render_config())["tools"]["allow"] == ["gaa__*"]
