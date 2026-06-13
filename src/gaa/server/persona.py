"""Persona + self-memory: SOUL.md (who the agent is) and MEMORY.md (what it remembers).

Cloned from the OpenClaw agent. Both files live in a persona dir under the cache,
are seeded from package data on first boot, are editable at runtime (self_edit), and
are persisted to vStorage (see gaa.persist). assemble_system_prompt() builds the
per-request system prompt from them + red-lines + the tool guide.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import gaa as _gaa

_FILES = ("SOUL.md", "MEMORY.md")

# Red-lines cloned from the workspace AGENTS.md (Plan 3), minus the OpenClaw "budgets"
# rule (analysis now runs in-process).
_REDLINES = """\
OPERATING RULES:
- Ground every analytical claim in evidence the tools produced. Do not invent numbers.
- Reuse the active run_id for drilldowns and follow-ups (it appears in the conversation).
- Tier-3 ad-hoc code is read-only on inputs; never mutate source metrics.
- Never echo secrets, tokens, or credentials.
"""

_PROTOCOL = """\
You act by emitting EXACTLY ONE JSON object per turn, either:
  {"action": "<name>", "args": { ... }}   to call a tool, or
  {"final": "<your message to the user>"}  to answer.
After a tool runs, its result is appended to the conversation and you continue.
When an analysis run is ready, end your final message naturally; the run is delivered
to the user as an interactive dossier automatically.
"""

# Tool guide. Analysis tools are always available; dangerous tools only when admin=True.
_ANALYSIS_TOOLS = """\
ANALYSIS TOOLS:
- analyze {query, session?}            start a new analysis (runs to completion)
- segments {run, dimension?}           decompose the change by a dimension
- detect {run, metric?}                anomaly/change-point detection
- market {run}                         genre/market benchmark comparison
- signals {run}                        competitor signals
- synth {run, question?}               (re)synthesize the hypothesis
- report {run}                         (re)render the dossier
- status {run} / jobs {}               inspect runs
- onboard_propose {csv} / profile_list {}   onboarding + profile inspection
- config_get {key?} / tools_list {} / tools_show {name} / doctor {}   inspection
"""

_ADMIN_TOOLS = """\
ADMIN TOOLS (you have admin rights this session):
- exec {command}                       run a shell command on the host
- browse {url}                         fetch a web page and read its text
- self_edit {target, content, mode?}   rewrite SOUL.md or MEMORY.md (mode: replace|append)
- config_set {key, value} / profile_use {name} / onboard_confirm {...}
- tools_promote {name, description, script, run?} / tools_run {name, run?, args?}
- tools_remove {name} / tools_import {tarball}
"""


def persona_dir(ctx) -> Path:
    return Path(ctx.settings.cache_dir) / "persona"


def _seed_dir() -> Path:
    return Path(os.path.dirname(_gaa.__file__)) / "data" / "seed"


def ensure_seeded(ctx) -> None:
    """Copy seed SOUL.md/MEMORY.md into the persona dir if absent (never clobber)."""
    d = persona_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        dest = d / name
        if not dest.exists():
            src = _seed_dir() / name
            if src.exists():
                shutil.copyfile(src, dest)


def _read(ctx, name: str) -> str:
    p = persona_dir(ctx) / name
    return p.read_text() if p.exists() else ""


def load_soul(ctx) -> str:
    return _read(ctx, "SOUL.md")


def load_memory(ctx) -> str:
    return _read(ctx, "MEMORY.md")


def write_persona(ctx, target: str, content: str, *, mode: str = "replace") -> int:
    """Write SOUL.md or MEMORY.md. Returns bytes written. Rejects any other target."""
    if target not in _FILES:
        raise ValueError(f"persona target must be one of {_FILES}, got {target!r}")
    d = persona_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    p = d / target
    if mode == "append":
        existing = p.read_text() if p.exists() else ""
        content = existing + ("\n" if existing and not existing.endswith("\n") else "") + content
    elif mode != "replace":
        raise ValueError(f"mode must be 'replace' or 'append', got {mode!r}")
    p.write_text(content)
    return len(content.encode("utf-8"))


def assemble_system_prompt(ctx, *, admin: bool) -> str:
    parts = [
        load_soul(ctx).strip(),
        "## MEMORY\n" + load_memory(ctx).strip(),
        _REDLINES,
        _PROTOCOL,
        _ANALYSIS_TOOLS,
    ]
    if admin:
        parts.append(_ADMIN_TOOLS)
    return "\n\n".join(p for p in parts if p)
