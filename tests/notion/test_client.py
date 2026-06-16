import json

import httpx
import pytest

from gaa.notion.client import NotionClient, NotionError
from tests.notion.conftest import make_client


def test_search_sends_auth_version_and_returns_results():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["version"] = request.headers.get("Notion-Version")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"id": "p1", "object": "page"}]})

    client = make_client(handler)
    results = client.search("patch notes", type="page", limit=5)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.notion.com/v1/search"
    assert captured["auth"] == "Bearer ntn_test"
    assert captured["version"] == "2025-09-03"
    assert results == [{"id": "p1", "object": "page"}]
    assert captured["body"]["query"] == "patch notes"
    assert captured["body"]["page_size"] == 5
    assert captured["body"]["filter"] == {"value": "page", "property": "object"}


def test_http_error_raises_notion_error_with_status():
    def handler(request):
        return httpx.Response(404, json={"object": "error", "code": "object_not_found",
                                         "message": "Could not find data source"})

    client = make_client(handler)
    with pytest.raises(NotionError) as exc:
        client.search("x")
    assert exc.value.http_status == 404
    assert "Could not find data source" in exc.value.message


def test_rate_limit_surfaces_retry_after():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "30"}, json={})

    client = make_client(handler)
    with pytest.raises(NotionError) as exc:
        client.search("x")
    assert exc.value.http_status == 429
    assert exc.value.retry_after == 30.0


def test_get_data_source_query_page_and_blocks():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path == "/v1/data_sources/ds1":
            return httpx.Response(200, json={"id": "ds1", "properties": {"Name": {"type": "title"}}})
        if path == "/v1/data_sources/ds1/query":
            return httpx.Response(200, json={"results": [{"id": "row1"}]})
        if path == "/v1/pages/pg1":
            return httpx.Response(200, json={"id": "pg1", "object": "page"})
        if path == "/v1/blocks/pg1/children":
            return httpx.Response(200, json={"results": [{"type": "paragraph"}]})
        return httpx.Response(500, json={})

    client = make_client(handler)
    assert client.get_data_source("ds1")["id"] == "ds1"
    assert client.query_data_source("ds1", page_size=5) == [{"id": "row1"}]
    assert client.get_page("pg1")["object"] == "page"
    assert client.get_block_children("pg1") == [{"type": "paragraph"}]
    assert ("POST", "/v1/data_sources/ds1/query") in seen
    assert ("GET", "/v1/blocks/pg1/children") in seen


def test_query_data_source_passes_sorts():
    captured = {}

    def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    client = make_client(handler)
    client.query_data_source("ds1", sorts=[{"property": "Go-live Date", "direction": "descending"}],
                             page_size=25)
    assert captured["body"]["sorts"] == [{"property": "Go-live Date", "direction": "descending"}]
    assert captured["body"]["page_size"] == 25
