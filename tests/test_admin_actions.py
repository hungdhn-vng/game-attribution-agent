import pytest

from gaa.admin_actions import AdminActions, ADMIN_ACTIONS, MAX_BEHAVIOR_CHARS
from gaa.schema.profile import ColumnMapping, GameProfile
from gaa.store.config_store import ConfigStore
from gaa.store.profile_store import ProfileStore


def make_profile(name: str) -> GameProfile:
    return GameProfile(
        name=name, platform="Custom", genre="survival",
        mapping=ColumnMapping(date_col="date", metric_cols={"rev": "revenue"}),
    )


@pytest.fixture
def admin(tmp_path):
    config = ConfigStore(str(tmp_path / "db.sqlite"))
    profiles = ProfileStore(str(tmp_path / "db.sqlite"))
    return AdminActions(config=config, profiles=profiles, admin_key="sekret"), config, profiles


def test_disabled_without_key(tmp_path):
    a = AdminActions(
        config=ConfigStore(str(tmp_path / "x.sqlite")),
        profiles=ProfileStore(str(tmp_path / "x.sqlite")),
        admin_key="",
    )
    out = a.handle("admin_get_config", {"admin_key": "anything"})
    assert out["status"] == "error" and "disabled" in out["error"]


def test_wrong_key_rejected(admin):
    a, _, _ = admin
    out = a.handle("admin_get_config", {"admin_key": "wrong"})
    assert out == {"status": "error", "code": 403, "error": "not authorized"}


def test_get_config(admin):
    a, _, _ = admin
    out = a.handle("admin_get_config", {"admin_key": "sekret"})
    assert out["status"] == "success"
    assert out["config"]["benchmark_mode"]["value"] == "snapshot"


def test_set_config_roundtrip(admin):
    a, config, _ = admin
    out = a.handle("admin_set_config",
                   {"admin_key": "sekret", "config": {"benchmark_mode": "crawl"}})
    assert out["status"] == "success"
    assert config.resolve("benchmark_mode") == ("crawl", "store")
    assert out["config"]["benchmark_mode"]["value"] == "crawl"


def test_set_config_validates(admin):
    a, _, _ = admin
    out = a.handle("admin_set_config",
                   {"admin_key": "sekret", "config": {"benchmark_mode": "banana"}})
    assert out["status"] == "error" and "benchmark_mode" in out["error"]
    out = a.handle("admin_set_config", {"admin_key": "sekret", "config": {}})
    assert out["status"] == "error"


def test_set_behavior_and_cap(admin):
    a, config, _ = admin
    out = a.handle("admin_set_behavior",
                   {"admin_key": "sekret", "instructions": "Answer in Vietnamese."})
    assert out["status"] == "success"
    assert config.resolve("behavior_instructions")[0] == "Answer in Vietnamese."
    out = a.handle("admin_set_behavior",
                   {"admin_key": "sekret", "instructions": "x" * (MAX_BEHAVIOR_CHARS + 1)})
    assert out["status"] == "error" and "too long" in out["error"]


def test_profiles_list_and_activate(admin):
    a, _, profiles = admin
    profiles.save(make_profile("alpha"))
    profiles.save(make_profile("beta"))
    profiles.set_active("alpha")

    out = a.handle("list_profiles", {"admin_key": "sekret"})
    assert out["profiles"] == ["alpha", "beta"] and out["active"] == "alpha"

    out = a.handle("set_active_profile", {"admin_key": "sekret", "name": "beta"})
    assert out["status"] == "success" and out["active"] == "beta"
    assert profiles.get_active().name == "beta"

    out = a.handle("set_active_profile", {"admin_key": "sekret", "name": "ghost"})
    assert out["status"] == "error"


def test_action_set_is_complete():
    assert ADMIN_ACTIONS == {"admin_get_config", "admin_set_config",
                             "admin_set_behavior", "list_profiles",
                             "set_active_profile"}


def test_unknown_action_rejected(admin):
    a, _, _ = admin
    out = a.handle("config", {"admin_key": "sekret"})
    assert out["status"] == "error" and "unknown admin action" in out["error"]
