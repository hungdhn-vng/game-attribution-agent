import httpx

from gaa.notion import tools
from tests.notion.conftest import mock_tools


def test_build_updates_structured_data_source_path(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/data_sources/buildsds":
            return httpx.Response(200, json={"name": [{"plain_text": "04_LiveOps Calendar Content"}],
                                             "properties": {
                                                 "Event Name": {"type": "title"},
                                                 "Go-live Date": {"type": "date"},
                                                 "Version": {"type": "rich_text"},
                                                 "Brief": {"type": "rich_text"},
                                             }})
        if path == "/v1/data_sources/buildsds/query":
            return httpx.Response(200, json={"results": [
                {"url": "https://n/r1", "created_time": "2026-05-10T00:00:00.000Z",
                 "properties": {
                     "Event Name": {"type": "title", "title": [{"plain_text": "Spring patch"}]},
                     "Go-live Date": {"type": "date", "date": {"start": "2026-05-10"}},
                     "Version": {"type": "rich_text", "rich_text": [{"plain_text": "1.2"}]},
                     "Brief": {"type": "rich_text", "rich_text": [{"plain_text": "Big balance changes and bugfixes"}]},
                 }},
            ]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler, env={"NOTION_BUILDS_DS": "buildsds"})
    out = tools.run_tool("build_updates", {"since": "2026-05-01", "until": "2026-05-31"})
    assert out["status"] == "success"
    assert out["source"] == "data_source"
    item = out["items"][0]
    assert item["date"] == "2026-05-10"
    assert item["title"] == "Spring patch"
    assert item["version"] == "1.2"
    assert "balance" in item["summary"]


def test_build_updates_date_filter_excludes_out_of_range(monkeypatch):
    def handler(request):
        if request.url.path == "/v1/data_sources/buildsds":
            return httpx.Response(200, json={"properties": {
                "Event Name": {"type": "title"}, "Go-live Date": {"type": "date"}}})
        return httpx.Response(200, json={"results": [
            {"url": "u1", "properties": {"Event Name": {"type": "title", "title": [{"plain_text": "old"}]},
                                         "Go-live Date": {"type": "date", "date": {"start": "2026-01-01"}}}},
            {"url": "u2", "properties": {"Event Name": {"type": "title", "title": [{"plain_text": "new"}]},
                                         "Go-live Date": {"type": "date", "date": {"start": "2026-05-15"}}}},
        ]})
    mock_tools(monkeypatch, handler, env={"NOTION_BUILDS_DS": "buildsds"})
    out = tools.run_tool("build_updates", {"since": "2026-05-01"})
    titles = [i["title"] for i in out["items"]]
    assert titles == ["new"]


def test_user_sentiment_no_date_prop_uses_created_time(monkeypatch):
    """Mirrors 10_Discord Sentiment: title=Report, text=note, NO date property."""
    def handler(request):
        path = request.url.path
        if path == "/v1/data_sources/sentds":
            return httpx.Response(200, json={"name": [{"plain_text": "10_Discord Sentiment"}],
                                             "properties": {
                                                 "Report": {"type": "title"},
                                                 "note": {"type": "rich_text"},
                                                 "Created time": {"type": "created_time"}}})
        return httpx.Response(200, json={"results": [
            {"url": "https://n/s1", "created_time": "2026-06-15T02:06:00.000Z",
             "properties": {
                 "Report": {"type": "title", "title": [{"plain_text": "Week 25 sentiment"}]},
                 "note": {"type": "rich_text", "rich_text": [{"plain_text": "Players love the new map"}]}}}]})
    mock_tools(monkeypatch, handler, env={"NOTION_SENTIMENT_DS": "sentds"})
    out = tools.run_tool("user_sentiment", {})
    assert out["status"] == "success"
    assert out["source"] == "data_source"
    item = out["items"][0]
    assert item["date"] == "2026-06-15"        # fell back to created_time
    assert item["source"] == "Week 25 sentiment"
    assert "love" in item["snippet"]


def test_user_sentiment_search_fallback_when_no_db(monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/search":
            return httpx.Response(200, json={"results": [
                {"object": "page", "id": "p1", "url": "https://n/p1",
                 "created_time": "2026-05-09T00:00:00.000Z",
                 "properties": {"Report": {"type": "title", "title": [{"plain_text": "Reddit thread"}]}}},
            ]})
        if path == "/v1/blocks/p1/children":
            return httpx.Response(200, json={"results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Players love the new map."}]}}]})
        return httpx.Response(500, json={})
    mock_tools(monkeypatch, handler)  # no NOTION_SENTIMENT_DS
    out = tools.run_tool("user_sentiment", {})
    assert out["status"] == "success"
    assert out["source"] == "search"
    item = out["items"][0]
    assert item["date"] == "2026-05-09"
    assert item["source"] == "Reddit thread"
    assert "love" in item["snippet"]
