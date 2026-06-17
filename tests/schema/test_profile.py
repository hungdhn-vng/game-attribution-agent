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


def test_profile_round_trips_with_plan():
    from gaa.core.schema.profile import GameProfile
    from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
    plan = IngestionPlan(read_spec=ReadSpec(format="excel", sheet="Data"),
                         orientation="wide", date_col="date",
                         metric_cols={"dau": "dau"}, confidence=0.9)
    p = GameProfile(name="g", platform="roblox", genre="rpg", plan=plan)
    again = GameProfile.model_validate_json(p.model_dump_json())
    assert again.plan.read_spec.sheet == "Data"
    assert again.plan.metric_cols["dau"] == "dau"
    assert again.mapping is None   # legacy field now optional
