from gaa.mcp import tools
from gaa.server import actions

def test_specs_include_core_analysis_tools():
    names = {t["name"] for t in tools.tool_specs(is_admin=False)}
    assert {"analyze", "segments", "report", "status"} <= names

def test_admin_tools_hidden_from_non_admin():
    non_admin = {t["name"] for t in tools.tool_specs(is_admin=False)}
    admin = {t["name"] for t in tools.tool_specs(is_admin=True)}
    exposed_admin = actions.ADMIN_ACTIONS & set(tools._SPECS)
    assert exposed_admin and exposed_admin <= admin
    assert not (exposed_admin & non_admin)

def test_every_spec_has_object_schema():
    for t in tools.tool_specs(is_admin=True):
        assert t["input_schema"]["type"] == "object"
        assert t["name"] not in {"exec", "browse", "self_edit"}
