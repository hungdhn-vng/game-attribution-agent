import httpx
import pytest
from gaa.appstore import search

_PAYLOAD = {"resultCount": 2, "results": [
    {"trackId": 1480616990, "trackName": "League of Legends: Wild Rift",
     "sellerName": "Riot Games", "primaryGenreName": "Games",
     "trackViewUrl": "https://apps.apple.com/app/id1480616990"},
    {"trackName": "No Track Id App"},  # missing trackId → must be skipped
]}

def _mount(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.Client
    monkeypatch.setattr(search.httpx, "Client", lambda *a, **k: real(*a, transport=transport, **k))

def test_maps_fields_and_query(monkeypatch):
    captured = {}
    def handler(req):
        captured["url"] = str(req.url)
        return httpx.Response(200, json=_PAYLOAD)
    _mount(monkeypatch, handler)
    apps = search.search_apps("MOBA", country="VN", limit=3)
    assert apps == [{
        "app_id": 1480616990, "name": "League of Legends: Wild Rift",
        "publisher": "Riot Games", "genre": "Games", "platform": "ios",
        "url": "https://apps.apple.com/app/id1480616990",
    }]  # the entry without trackId is dropped
    u = captured["url"]
    assert "term=MOBA" in u and "country=VN" in u and "limit=3" in u and "entity=software" in u

def test_empty_results(monkeypatch):
    _mount(monkeypatch, lambda req: httpx.Response(200, json={"resultCount": 0, "results": []}))
    assert search.search_apps("zzznomatch") == []

def test_non_200_raises(monkeypatch):
    _mount(monkeypatch, lambda req: httpx.Response(503, text="down"))
    with pytest.raises(httpx.HTTPError):
        search.search_apps("x")
