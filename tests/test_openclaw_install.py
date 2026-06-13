from pathlib import Path

WS = Path(__file__).resolve().parents[1] / "workspace"


def _read(rel):
    return (WS / rel).read_text()


def test_workspace_artifacts_exist():
    for rel in ["AGENTS.md", "skills/gaa/SKILL.md",
                "skills/gaa/references/analysis.md", "skills/gaa/references/drilldowns.md",
                "skills/gaa/references/adhoc.md", "skills/gaa/references/onboarding.md",
                "skills/gaa/references/admin.md", "skills/gaa/references/tools.md"]:
        assert (WS / rel).exists(), f"missing workspace artifact: {rel}"
        assert (WS / rel).read_text().strip(), f"empty workspace artifact: {rel}"


def test_no_dead_architecture_references():
    rels = ["AGENTS.md", "skills/gaa/SKILL.md"] + [
        f"skills/gaa/references/{n}.md" for n in
        ["analysis", "drilldowns", "adhoc", "onboarding", "admin", "tools"]]
    for rel in rels:
        text = _read(rel).lower()
        assert "gaa_endpoint" not in text, f"{rel} references the dead GAA_ENDPOINT"
        assert "admin_key" not in text, f"{rel} references the dead admin_key"
        assert "/invocations" not in text, f"{rel} references the dead HTTP endpoint"


def test_skill_teaches_env_sourcing():
    skill = _read("skills/gaa/SKILL.md")
    assert ". ./.env" in skill and "set -a" in skill
    assert "already loaded" not in skill.lower()


def test_skill_describes_the_cli_and_marker():
    skill = _read("skills/gaa/SKILL.md")
    assert "gaa analyze" in skill
    assert "[[gaa:run_id=" in skill
    assert "gaa jobs" in skill


def test_agents_md_has_redlines():
    agents = _read("AGENTS.md").lower()
    assert "admin:" in agents
    assert ".env" in agents
    assert "run id" in agents or "run_id" in agents


def test_adhoc_reference_states_readonly_and_verbatim():
    adhoc = _read("skills/gaa/references/adhoc.md").lower()
    assert "gaa.lab" in adhoc
    assert "read-only" in adhoc or "read only" in adhoc
    assert "verbatim" in adhoc or "never report a number" in adhoc


import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "openclaw_install",
    Path(__file__).resolve().parents[1] / "scripts" / "openclaw_install.py")


def _mod():
    m = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(m)
    return m


def test_collect_workspace_files_walks_tree(tmp_path):
    inst = _mod()
    ws = tmp_path / "workspace"
    (ws / "skills" / "gaa" / "references").mkdir(parents=True)
    (ws / "AGENTS.md").write_text("a")
    (ws / "skills" / "gaa" / "SKILL.md").write_text("b")
    (ws / "skills" / "gaa" / "references" / "analysis.md").write_text("c")
    files = inst.collect_workspace_files(str(ws))
    assert files["AGENTS.md"] == "a"
    assert files["skills/gaa/SKILL.md"] == "b"
    assert files["skills/gaa/references/analysis.md"] == "c"


def test_md5_matches_hashlib(tmp_path):
    inst = _mod()
    import hashlib
    assert inst._md5("hello") == hashlib.md5(b"hello").hexdigest()


def test_splice_http_endpoint_inserts_once():
    inst = _mod()
    raw = "module.exports = {\n    bind: 'lan',\n    other: 1,\n}\n"
    out = inst.splice_http_endpoint(raw)
    assert "chatCompletions" in out
    assert inst.splice_http_endpoint(out) == out


def test_workspace_env_excludes_dead_keys():
    inst = _mod()
    env = inst.render_workspace_env({"LLM_API_KEY": "k", "LLM_MODEL": "qwen",
                                     "PERPLEXITY_API_KEY": "p", "GAA_BENCHMARK_MODE": "crawl"})
    assert "LLM_API_KEY=k" in env and "GAA_BENCHMARK_MODE=crawl" in env
    assert "GAA_ENDPOINT" not in env
    assert "GAA_ADMIN_KEY" not in env


def test_dry_run_manifest_lists_files_and_capability_gate(capsys, tmp_path, monkeypatch):
    inst = _mod()
    ws = tmp_path / "workspace"
    (ws / "skills" / "gaa").mkdir(parents=True)
    (ws / "AGENTS.md").write_text("a")
    (ws / "skills" / "gaa" / "SKILL.md").write_text("b")
    monkeypatch.setenv("GAA_REPO_URL", "https://example.com/repo.git")
    inst.main(["--dry-run", "--workspace", str(ws)])
    out = capsys.readouterr().out
    assert "AGENTS.md" in out and "skills/gaa/SKILL.md" in out
    assert "pip install -e ." in out
    assert "gaa doctor" in out
