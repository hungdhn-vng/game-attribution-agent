import io
import json
import os
from contextlib import redirect_stdout

from gaa.cli.main import main


def _run(tmp_path, monkeypatch, with_key: bool):
    os.environ["GAA_DB_PATH"] = str(tmp_path / "gaa.sqlite")
    os.environ["GAA_CACHE_DIR"] = str(tmp_path / "cache")
    os.environ["GAA_CONFIG_PATH"] = str(tmp_path / "gaa-config.toml")
    if with_key:
        monkeypatch.setenv("LLM_API_KEY", "k")
    else:
        monkeypatch.delenv("LLM_API_KEY", raising=False)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["doctor"], today="2026-06-13")
    return json.loads(buf.getvalue())


def test_doctor_reports_checks(tmp_path, monkeypatch):
    resp = _run(tmp_path, monkeypatch, with_key=True)
    names = {c["name"] for c in resp["checks"]}
    assert "dep:statsmodels" in names
    assert "dep:ruptures" in names
    assert "config" in names
    assert "active_profile" in names
    assert "llm_credentials" in names
    assert resp["ok"] is True  # no active profile / key are warnings, not errors


def test_doctor_hard_ok_independent_of_warnings(tmp_path, monkeypatch):
    resp = _run(tmp_path, monkeypatch, with_key=False)
    assert resp["status"] == "success"
    assert resp["ok"] is True
    llm = next(c for c in resp["checks"] if c["name"] == "llm_credentials")
    assert llm["ok"] is False and llm["level"] == "warn"
    prof = next(c for c in resp["checks"] if c["name"] == "active_profile")
    assert prof["ok"] is False and prof["level"] == "warn"


def test_doctor_stores_check_probes(tmp_path, monkeypatch):
    resp = _run(tmp_path, monkeypatch, with_key=True)
    stores = next(c for c in resp["checks"] if c["name"] == "stores")
    assert stores["ok"] is True
    # detail must reflect a real probe (writable path), not a hardcoded "ok"
    assert "writable" in stores["detail"]
