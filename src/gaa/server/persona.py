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

_STANDARD_SESSION = """\
SESSION PRIVILEGES: This is a standard (non-admin) session. You do NOT have admin rights
right now, so admin-only capabilities (running shell commands, browsing the web, editing
your own files, changing config or profiles) are unavailable to you. If the user asks
whether they're an admin or what they're allowed to do, answer plainly from this fact —
do not call tools to find out.
"""

_THOUGHT_HINT = """\
THINKING: Include a "thought" field (1-2 sentences explaining your reasoning for this
step) alongside your decision, e.g. {"thought": "…", "action": "…", "args": {…}} or
{"thought": "…", "final": "…"}. The thought is shown to the user as your reasoning; it
does not replace the action/final.
"""


def reasoning_enabled() -> bool:
    """Whether /chat reveals the agent's reasoning as `thinking` SSE events.

    Default ON. Set GAA_STREAM_REASONING to 0/false/no/off to disable (falls back to
    exactly the prior behavior — no `thought` asked for, no thinking events emitted).
    """
    return os.environ.get("GAA_STREAM_REASONING", "1").strip().lower() not in (
        "0", "false", "no", "off")


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
    return p.read_text(encoding="utf-8") if p.exists() else ""


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
        existing = p.read_text(encoding="utf-8") if p.exists() else ""
        content = existing + ("\n" if existing and not existing.endswith("\n") else "") + content
    elif mode != "replace":
        raise ValueError(f"mode must be 'replace' or 'append', got {mode!r}")
    p.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def assemble_system_prompt(ctx, *, admin: bool) -> str:
    soul = load_soul(ctx).strip()
    memory = load_memory(ctx).strip()
    parts = [soul]
    if memory:
        parts.append("## MEMORY\n" + memory)
    parts += [_REDLINES, _PROTOCOL]
    if reasoning_enabled():
        parts.append(_THOUGHT_HINT)
    parts.append(_ANALYSIS_TOOLS)
    if admin:
        parts.append(_ADMIN_TOOLS)
    else:
        parts.append(_STANDARD_SESSION)
    return "\n\n".join(p for p in parts if p)
