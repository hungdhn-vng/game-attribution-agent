import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _env(tmp_path):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    os.environ["GAA_TOOLS_DIR"] = str(tmp_path / "cache" / "tools")


def _run(argv, tmp_path):
    _env(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(argv, today="2026-06-13")
    return json.loads(buf.getvalue())


def _script(tmp_path, body="print('hi')\n"):
    p = tmp_path / "scratch.py"
    p.write_text(body)
    return str(p)


def test_tools_promote(tmp_path):
    resp = _run(["tools", "promote", "--name", "t", "--description", "d",
                 "--script", _script(tmp_path)], tmp_path)
    assert resp["status"] == "success"
    assert resp["tool"] == "t" and resp["md5"]


def test_tools_promote_missing_script_is_error(tmp_path):
    resp = _run(["tools", "promote", "--name", "t", "--description", "d",
                 "--script", str(tmp_path / "nope.py")], tmp_path)
    assert resp["status"] == "error"
