import httpx

from gaa.notion import tools
from tests.notion.conftest import mock_tools


def test_tool_specs_are_the_four_read_tools():
    names = {t["name"] for t in tools.tool_specs()}
    assert names == {"build_updates", "user_sentiment", "notion_search", "notion_fetch"}
    for t in tools.tool_specs():
        assert t["input_schema"]["type"] == "object"


def test_notion_search_type_enum_is_page_or_data_source():
    spec = {t["name"]: t for t in tools.tool_specs()}["notion_search"]
    assert spec["input_schema"]["properties"]["type"]["enum"] == ["page", "data_source"]


def test_unknown_tool_is_structured_error():
    assert tools.run_tool("nope", {})["status"] == "error"


def test_missing_token_is_structured_error(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    out = tools.run_tool("notion_search", {"query": "x"})
    assert out == {"status": "error", "error": "notion token not configured"}


def test_invalid_args_rejected_by_schema(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "ntn_test")
    out = tools.run_tool("notion_search", {})  # query is required
    assert out["status"] == "error"
    assert "invalid args" in out["error"]


def test_notion_error_is_mapped_to_structured_result(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"object": "error", "code": "unauthorized",
                                         "message": "API token is invalid."})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_search", {"query": "x"})
    assert out["status"] == "error"
    assert out["http_status"] == 401
    assert "invalid" in out["error"]


def test_normalize_id_extracts_from_url():
    assert tools._normalize_id(
        "https://app.notion.com/p/Event-37c0e4e2394280938d60defc532e5ad8"
    ) == "37c0e4e2394280938d60defc532e5ad8"
    assert tools._normalize_id(
        "abee2267-021c-4a98-b91b-95d71e2a0cee"
    ) == "abee2267021c4a98b91b95d71e2a0cee"
    assert tools._normalize_id("plainid") == "plainid"
    assert tools._normalize_id(
        "https://www.notion.so/ws/Archive-37c0e4e2394280938d60defc532e5ad8"
    ) == "37c0e4e2394280938d60defc532e5ad8"


def test_plain_extracts_common_property_types():
    assert tools._plain({"type": "title", "title": [{"plain_text": "Hi"}]}) == "Hi"
    assert tools._plain({"type": "rich_text", "rich_text": [{"plain_text": "a"}, {"plain_text": "b"}]}) == "ab"
    assert tools._plain({"type": "date", "date": {"start": "2026-05-01"}}) == "2026-05-01"
    assert tools._plain({"type": "select", "select": {"name": "Q3 2026"}}) == "Q3 2026"
    assert tools._plain({"type": "status", "status": {"name": "Not started"}}) == "Not started"
    assert tools._plain({"type": "multi_select",
                         "multi_select": [{"name": "PC"}, {"name": "Mobile"}]}) == "PC, Mobile"
    assert tools._plain({"type": "created_time", "created_time": "2026-06-15T02:06:00.000Z"}) == "2026-06-15T02:06:00.000Z"
    assert tools._plain({"type": "number", "number": 7}) == "7"
    assert tools._plain({"type": "unique_id", "unique_id": {"prefix": "PROJ", "number": 5}}) == "PROJ-5"
    assert tools._plain({"type": "unique_id", "unique_id": {"prefix": "PROJ", "number": None}}) == ""


def test_notion_search_shapes_hits(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"object": "page", "id": "p1", "url": "https://n/p1",
             "properties": {"Event Name": {"type": "title", "title": [{"plain_text": "Patch 1.2"}]}}},
            {"object": "data_source", "id": "d1", "url": "https://n/d1",
             "name": [{"plain_text": "Releases"}]},
        ]})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_search", {"query": "patch"})
    assert out["status"] == "success"
    assert out["results"][0] == {"id": "p1", "type": "page", "title": "Patch 1.2", "url": "https://n/p1"}
    assert out["results"][1]["title"] == "Releases"
    assert out["results"][1]["type"] == "data_source"


def test_notion_fetch_page_returns_text(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/pages/abc":
            return httpx.Response(200, json={"object": "page", "id": "abc", "url": "https://n/abc",
                                             "properties": {"Event Name": {"type": "title",
                                                                           "title": [{"plain_text": "Notes"}]}}})
        if path == "/v1/blocks/abc/children":
            return httpx.Response(200, json={"results": [
                {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Build 5"}]}},
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Fixed crash."}]}},
            ]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_fetch", {"id": "abc"})
    assert out["status"] == "success"
    assert out["kind"] == "page"
    assert out["title"] == "Notes"
    assert out["text"] == "Build 5\nFixed crash."


def test_notion_fetch_falls_back_to_data_source(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/pages/ds9":
            return httpx.Response(404, json={"object": "error", "code": "object_not_found",
                                             "message": "Could not find page"})
        if path == "/v1/data_sources/ds9":
            return httpx.Response(200, json={"id": "ds9", "url": "https://n/ds9",
                                             "name": [{"plain_text": "Feedback"}]})
        if path == "/v1/data_sources/ds9/query":
            return httpx.Response(200, json={"results": [
                {"id": "r1", "url": "https://n/r1",
                 "properties": {"note": {"type": "rich_text", "rich_text": [{"plain_text": "great"}]}}},
            ]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler)
    out = tools.run_tool("notion_fetch", {"id": "ds9"})
    assert out["status"] == "success"
    assert out["kind"] == "data_source"
    assert out["title"] == "Feedback"
    assert out["rows"][0]["properties"]["note"] == "great"
