import json, os, stat
import pytest
from gaa.server import extensions as ext


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ext, "_dir", lambda: tmp_path)
    yield


def test_add_list_remove_server():
    ext.add_server(name="crawler", command="npx", args=["x-mcp"], url=None,
                   env={"CRAWLER_KEY": "CRAWLER_KEY"})
    assert [s["name"] for s in ext.list_servers()] == ["crawler"]
    ext.remove_server("crawler")
    assert ext.list_servers() == []


def test_add_server_rejects_bad_name():
    with pytest.raises(ValueError):
        ext.add_server(name="has space", command="x", args=[], url=None, env={})


def test_add_server_requires_command_or_url():
    with pytest.raises(ValueError):
        ext.add_server(name="x", command=None, args=[], url=None, env={})


def test_secret_roundtrip_and_names_only():
    ext.set_secret("CRAWLER_KEY", "s3cr3t-value")
    assert ext.list_secret_names() == ["CRAWLER_KEY"]
    assert ext.get_secret("CRAWLER_KEY") == "s3cr3t-value"
    ext.unset_secret("CRAWLER_KEY")
    assert ext.list_secret_names() == []


def test_secret_file_mode_600(tmp_path):
    ext.set_secret("K", "v")
    mode = stat.S_IMODE(os.stat(ext.secrets_path()).st_mode)
    assert mode == 0o600
