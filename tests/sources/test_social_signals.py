from gaa.core.sources.social_signals import SocialSignalProvider

_JSON = ('{"signals": ['
         '{"date": "2026-06-04", "kind": "influencer", "scope": "game", '
         '"entity": "BigTuber (3M)", "reach": "1.2M views", "url": "https://yt", '
         '"summary": "featured the game", "sentiment": 0.5},'
         '{"date": "2026-05-01", "kind": "social_trend", "scope": "genre", '
         '"entity": "TikTok", "reach": "", "url": "https://tt", '
         '"summary": "genre buzz", "sentiment": 0.1}]}')


def test_parses_and_window_filters():
    prov = SocialSignalProvider(lambda p: {"content": _JSON, "citations": []})
    out = prov.events("Real Game", "rpg", "2026-06-01", "2026-06-08")
    assert len(out) == 1                       # the 05-01 genre signal is out of window
    ev = out[0]
    assert ev["kind"] == "influencer" and ev["scope"] == "game"
    assert ev["entity"] == "BigTuber (3M)" and ev["url"] == "https://yt"
    assert ev["title"]                         # title populated for CompetitorSignals


def test_unparseable_returns_empty_list():
    assert SocialSignalProvider(lambda p: {"content": "nope", "citations": []}).events(
        "g", "rpg", "2026-06-01", "2026-06-08") == []
