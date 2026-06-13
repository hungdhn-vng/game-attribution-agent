from gaa.core.schema.profile import ColumnMapping, GameProfile


def test_column_mapping_roundtrip():
    m = ColumnMapping(
        date_col="dt",
        metric_cols={"dau_count": "dau", "rev": "revenue"},
        dim_cols={"country": "region", "app_version": "version"},
    )
    assert m.metric_cols["dau_count"] == "dau"
    assert ColumnMapping(**m.model_dump()) == m


def test_game_profile_defaults():
    p = GameProfile(
        name="MyGame",
        platform="roblox",
        genre="survival",
        mapping=ColumnMapping(date_col="dt", metric_cols={"dau_count": "dau"}, dim_cols={}),
    )
    assert p.external_source_config == {}
    assert p.created_at  # auto-stamped ISO string
    assert GameProfile(**p.model_dump()).name == "MyGame"


def test_mapping_rejects_unknown_canonical_metric_field():
    import pytest
    with pytest.raises(ValueError):
        ColumnMapping(date_col="dt", metric_cols={"x": ""}, dim_cols={})
