import pandas as pd
from gaa.core.modules.competitor_signals import CompetitorSignals
from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _ctx(title=None):
    prof = GameProfile(name="csv-key", platform="roblox", genre="rpg", title=title,
                       mapping=ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={}))
    df = pd.DataFrame({"date": pd.to_datetime(["2026-06-04"]), "metric": ["dau"], "value": [1.0]})
    for c in ["platform", "region", "version", "cohort", "device", "source"]:
        df[c] = None
    return AnalysisContext(profile=prof, metrics=df, query="q", metric="dau",
                           start="2026-06-01", end="2026-06-08")


class _Src:
    def __init__(self, events, recorder=None):
        self._events, self._rec = events, recorder
    def events(self, game, genre, start, end):
        if self._rec is not None:
            self._rec.append(game)
        return self._events


def test_game_scoped_influencer_becomes_external_entry():
    ev = [{"date": "2026-06-04", "kind": "influencer", "scope": "game",
           "entity": "BigTuber", "reach": "1.2M", "url": "https://yt",
           "summary": "featured the game", "sentiment": 0.5, "title": "featured the game"}]
    led = EvidenceLedger()
    CompetitorSignals(_Src(ev)).run(_ctx(), led)
    e = [x for x in led.all() if x.module == "competitor"][0]
    assert e.source_type == "external" and "(influencer)" in e.claim
    assert "BigTuber" in e.claim and e.source == "https://yt"


def test_passes_profile_title_to_source():
    rec = []
    CompetitorSignals(_Src([], recorder=rec)).run(_ctx(title="Real Game Name"), EvidenceLedger())
    assert rec == ["Real Game Name"]


def test_legacy_event_without_scope_keeps_old_format():
    ev = [{"date": "2026-06-04", "kind": "patch", "title": "v2 released",
           "url": "https://u", "sentiment": 0.0}]
    led = EvidenceLedger()
    CompetitorSignals(_Src(ev)).run(_ctx(), led)
    assert any(x.claim == "patch: v2 released" for x in led.all())


def test_no_events_records_gap():
    # graceful "no signals" path (the common production case) — preserved from
    # the prior test file that this one replaced.
    led = EvidenceLedger()
    CompetitorSignals(_Src([])).run(_ctx(), led)
    assert any(e.source_type == "derived" and e.strength == "low" for e in led.all())


def test_legacy_events_logged_as_external_entries():
    ev = [{"date": "2026-06-04", "title": "Competitor Y soft-launch", "kind": "competitor",
           "url": "http://x", "sentiment": -0.3},
          {"date": "2026-06-05", "title": "v3.2 update notes", "kind": "patch",
           "url": "http://p", "sentiment": 0.0}]
    led = EvidenceLedger()
    CompetitorSignals(_Src(ev)).run(_ctx(), led)
    ext = [e for e in led.all() if e.module == "competitor" and e.source_type == "external"]
    assert len(ext) == 2 and any("Competitor Y" in e.claim for e in ext)
