from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource


def test_benchmark_returns_genre_series():
    b = FixtureBenchmarkSource(genre_index={"2026-05-01": 100.0, "2026-05-03": 98.0})
    s = b.genre_trend("survival", "2026-05-01", "2026-05-03")
    assert s["2026-05-03"] == 98.0


def test_signals_returns_events():
    src = FixtureSignalsSource(events=[
        {"date": "2026-04-28", "title": "Competitor Y soft-launch", "kind": "competitor",
         "url": "http://x", "sentiment": -0.2}])
    evs = src.events("MyGame", "survival", "2026-04-01", "2026-05-31")
    assert evs[0]["kind"] == "competitor"
