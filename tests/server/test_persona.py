import os
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.server import persona


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_ensure_seeded_copies_seeds(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    d = persona.persona_dir(ctx)
    assert (d / "SOUL.md").exists()
    assert (d / "MEMORY.md").exists()
    assert "becoming someone" in (d / "SOUL.md").read_text()


def test_ensure_seeded_does_not_clobber_existing(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    persona.write_persona(ctx, "MEMORY.md", "# MEMORY\n\nLearned: SurvivalGame is on roblox.\n")
    persona.ensure_seeded(ctx)  # second call must not overwrite
    assert "SurvivalGame" in persona.load_memory(ctx)


def test_assemble_system_prompt_includes_persona_and_guide(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    prompt = persona.assemble_system_prompt(ctx, admin=False)
    assert "becoming someone" in prompt          # SOUL.md
    assert "# MEMORY" in prompt                   # MEMORY.md
    assert '"action"' in prompt and '"final"' in prompt  # tool-loop protocol
    assert "analyze" in prompt                    # tool guide lists gaa actions


def test_assemble_system_prompt_admin_flag_exposes_dangerous_tools(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    non_admin = persona.assemble_system_prompt(ctx, admin=False)
    admin = persona.assemble_system_prompt(ctx, admin=True)
    assert "exec" not in non_admin
    assert "exec" in admin


def test_write_persona_rejects_unknown_target(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    try:
        persona.write_persona(ctx, "../escape.md", "x")
        assert False, "expected ValueError"
    except ValueError:
        pass
