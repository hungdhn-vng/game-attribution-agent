import pytest

from gaa.tools_registry import ToolRegistry


def _script(tmp_path, body="print('hi')\n"):
    p = tmp_path / "s.py"
    p.write_text(body)
    return str(p)


def test_promote_freezes_copy_with_md5_and_provenance(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    meta = reg.promote("arpu-split", "Split ARPU by weekend/weekday",
                       _script(tmp_path), source_run="run-1", source_script="scratch/01.py")
    assert meta["name"] == "arpu-split"
    assert meta["md5"]
    assert meta["provenance"]["source_run"] == "run-1"
    assert (tmp_path / "tools" / "arpu-split" / "tool.py").exists()
    assert (tmp_path / "tools" / "arpu-split" / "tool.toml").exists()
    assert reg.verify("arpu-split") is True


def test_verify_fails_after_tamper(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    reg.promote("t", "d", _script(tmp_path))
    (tmp_path / "tools" / "t" / "tool.py").write_text("print('tampered')\n")
    assert reg.verify("t") is False


def test_list_show_remove(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    reg.promote("t", "desc", _script(tmp_path))
    listed = reg.list()
    assert listed and listed[0]["name"] == "t" and listed[0]["md5_ok"] is True
    shown = reg.show("t")
    assert shown["description"] == "desc" and "print" in shown["source"]
    reg.remove("t")
    assert reg.list() == []
    with pytest.raises(ValueError):
        reg.show("t")


def test_promote_missing_script_raises(tmp_path):
    reg = ToolRegistry(str(tmp_path / "tools"))
    with pytest.raises(ValueError):
        reg.promote("t", "d", str(tmp_path / "does-not-exist.py"))
