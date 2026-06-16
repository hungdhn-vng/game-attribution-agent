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


def test_registered_servers_merged_into_both_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.server import extensions
    extensions.set_secret("CRAWLER_KEY", "zzz")
    extensions.add_server(name="crawler", command="npx", args=["x-mcp"], url=None,
                          env={"CRAWLER_KEY": "CRAWLER_KEY"})
    for profile in ("admin", "nonadmin"):
        cfg = json.loads(render_config(profile=profile))
        srv = cfg["mcp"]["servers"]["crawler"]
        assert srv["command"] == "npx" and srv["args"] == ["x-mcp"]
        assert srv["env"]["CRAWLER_KEY"] == "zzz"          # secret injected by value


def test_nonadmin_allowlist_includes_registered_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    from gaa.server import extensions
    extensions.add_server(name="crawler", command="npx", args=[], url=None, env={})
    cfg = json.loads(render_config(profile="nonadmin"))
    assert "crawler__*" in cfg["tools"]["allow"]           # shared with non-admin (wildcard form)
