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
