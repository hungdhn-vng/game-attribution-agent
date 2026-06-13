import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main
from gaa.core.schema.profile import GameProfile, ColumnMapping
from gaa.core.store.profile_store import ProfileStore


def _seed_two_profiles(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    ps = ProfileStore(os.environ["GAA_DB_PATH"])
    m = ColumnMapping(date_col="d", metric_cols={"dau": "dau"}, dim_cols={})
    ps.save(GameProfile(name="Alpha", platform="roblox", genre="rpg", mapping=m))
    ps.save(GameProfile(name="Beta", platform="steam", genre="fps", mapping=m))
    ps.set_active("Alpha")


def _run(argv, tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_profile_list(tmp_path):
    _seed_two_profiles(tmp_path)
    resp = _run(["profile", "list"], tmp_path)
    assert resp["status"] == "success"
    assert set(resp["profiles"]) == {"Alpha", "Beta"}
    assert resp["active"] == "Alpha"


def test_profile_use_switches_active(tmp_path):
    _seed_two_profiles(tmp_path)
    resp = _run(["profile", "use", "Beta"], tmp_path)
    assert resp["status"] == "success"
    assert resp["active"] == "Beta"
    assert _run(["profile", "list"], tmp_path)["active"] == "Beta"


def test_profile_use_unknown_is_error(tmp_path):
    _seed_two_profiles(tmp_path)
    resp = _run(["profile", "use", "Nope"], tmp_path)
    assert resp["status"] == "error"
    assert "unknown profile" in resp["error"].lower()
