from gaa.mcp import tools

def test_specs_include_core_analysis_tools():
    names = {t["name"] for t in tools.tool_specs(is_admin=False)}
    assert {"analyze", "segments", "report", "status"} <= names

def test_admin_tools_hidden_from_non_admin():
    non_admin = {t["name"] for t in tools.tool_specs(is_admin=False)}
    admin = {t["name"] for t in tools.tool_specs(is_admin=True)}
    assert "config_set" not in non_admin
    assert "config_set" in admin

def test_every_spec_has_object_schema():
    for t in tools.tool_specs(is_admin=True):
        assert t["input_schema"]["type"] == "object"
        assert "exec" not in t["name"] and "browse" not in t["name"]
