from gaa.mcp import tools

MGMT = {"mcp_add", "mcp_remove", "mcp_list", "secret_set", "secret_unset", "secret_list"}


def test_management_tools_listed_only_for_admin():
    admin_names = {t["name"] for t in tools.tool_specs(is_admin=True)}
    user_names = {t["name"] for t in tools.tool_specs(is_admin=False)}
    assert MGMT <= admin_names          # admin sees them
    assert not (MGMT & user_names)      # non-admin sees none


def test_management_tool_schemas_have_required_fields():
    specs = {t["name"]: t for t in tools.tool_specs(is_admin=True)}
    assert specs["mcp_add"]["input_schema"]["required"] == ["name"]
    assert specs["secret_set"]["input_schema"]["required"] == ["name", "value"]
