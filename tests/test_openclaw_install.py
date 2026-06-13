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
    for rel in ["SKILL.md", "references/analysis.md", "references/admin.md"]:
        text = _read(f"skills/gaa/{rel}").lower()
        assert "gaa_endpoint" not in text, f"{rel} references the dead GAA_ENDPOINT"
        assert "admin_key" not in text, f"{rel} references the dead admin_key"
        assert "/invocations" not in text, f"{rel} references the dead HTTP endpoint"


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
