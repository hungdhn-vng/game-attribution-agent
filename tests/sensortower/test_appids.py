from gaa.sensortower import appids

def test_set_get_resolve(tmp_path):
    db = str(tmp_path / "p.sqlite")
    appids.set_app_id(db, "mygame", "self", 12345, "app_id")
    appids.set_app_id(db, "mygame", "competitor:clash", 678, "product_id")
    assert appids.get_app_ids(db, "mygame") == {
        "self": {"id": 12345, "id_type": "app_id"},
        "competitor:clash": {"id": 678, "id_type": "product_id"},
    }
    assert appids.resolve(db, "mygame", "self") == {"id": 12345, "id_type": "app_id"}
    assert appids.resolve(db, "mygame", "missing") is None
    assert appids.get_app_ids(db, "other") == {}

def test_set_overwrites(tmp_path):
    db = str(tmp_path / "p.sqlite")
    appids.set_app_id(db, "g", "self", 1, "app_id")
    appids.set_app_id(db, "g", "self", 2, "app_id")
    assert appids.resolve(db, "g", "self")["id"] == 2
