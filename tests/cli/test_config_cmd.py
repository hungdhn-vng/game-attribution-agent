import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _run(argv, tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def test_config_get_all(tmp_path):
    resp = _run(["config", "get"], tmp_path)
    assert resp["status"] == "success"
    assert "benchmark_mode" in resp["config"]
    assert resp["config"]["benchmark_mode"]["origin"] == "default"


def test_config_set_then_get(tmp_path):
    set_resp = _run(["config", "set", "benchmark_mode", "crawl"], tmp_path)
    assert set_resp["status"] == "success"
    assert set_resp["config"]["benchmark_mode"]["value"] == "crawl"
    get_resp = _run(["config", "get", "benchmark_mode"], tmp_path)
    assert get_resp["value"] == "crawl"
    assert get_resp["origin"] == "store"


def test_config_set_invalid_is_error(tmp_path):
    resp = _run(["config", "set", "benchmark_mode", "bogus"], tmp_path)
    assert resp["status"] == "error"
    assert "one of" in resp["error"]


def test_config_set_secret_rejected(tmp_path):
    resp = _run(["config", "set", "perplexity_api_key", "pplx-x"], tmp_path)
    assert resp["status"] == "error"
    assert "secret" in resp["error"].lower()
