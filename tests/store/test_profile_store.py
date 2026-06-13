from gaa.core.store.profile_store import ProfileStore
from gaa.core.schema.profile import GameProfile, ColumnMapping


def _profile(name="MyGame"):
    return GameProfile(
        name=name, platform="roblox", genre="survival",
        mapping=ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={}),
    )


def test_save_and_get(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    store.save(_profile())
    got = store.get("MyGame")
    assert got is not None and got.name == "MyGame"
    assert got.mapping.metric_cols == {"DAU": "dau"}


def test_get_missing_returns_none(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    assert store.get("nope") is None


def test_active_profile_tracking(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    store.save(_profile("A"))
    store.save(_profile("B"))
    store.set_active("B")
    assert store.get_active().name == "B"
    assert sorted(store.list_names()) == ["A", "B"]


def test_save_overwrites_same_name(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    store.save(_profile())
    p2 = _profile()
    p2.genre = "rpg"
    store.save(p2)
    assert store.get("MyGame").genre == "rpg"
    assert store.list_names() == ["MyGame"]
