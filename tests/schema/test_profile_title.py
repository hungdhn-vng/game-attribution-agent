from gaa.core.schema.profile import GameProfile, ColumnMapping


def _mapping():
    return ColumnMapping(date_col="d", metric_cols={"x": "dau"}, dim_cols={})


def test_title_defaults_to_none_and_round_trips():
    p = GameProfile(name="csv-key", platform="roblox", genre="rpg", mapping=_mapping())
    assert p.title is None
    p2 = GameProfile.model_validate_json(
        GameProfile(name="csv-key", platform="roblox", genre="rpg",
                    mapping=_mapping(), title="Real Game Name").model_dump_json())
    assert p2.title == "Real Game Name"
