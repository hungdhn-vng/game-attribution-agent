#!/usr/bin/env sh
set -eu
# OPENCLAW_CONFIG_DIR is the ~/.openclaw directory where openclaw.json lives.
# (Do NOT use OPENCLAW_HOME — OpenClaw treats that as the parent of ~/.openclaw,
#  which would double the path and break config loading.)
OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/home/node/.openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_CONFIG_DIR}/workspace"
mkdir -p "$OPENCLAW_CONFIG_DIR" "$GAA_CACHE_DIR"
# Render the OpenClaw config each boot (idempotent)
python3 -c "import os; from gaa.server.openclaw_config import render_config; print(render_config(model=os.environ.get('LLM_MODEL','google/gemma-4-31b-it')))" > "$OPENCLAW_CONFIG_DIR/openclaw.json"
# Seed MEMORY.md on first boot (never clobber — user's memory is precious)
[ -f "$OPENCLAW_CONFIG_DIR/MEMORY.md" ] || cp "/opt/gaa/openclaw/MEMORY.md" "$OPENCLAW_CONFIG_DIR/MEMORY.md" 2>/dev/null || true
# Write GAA persona/rules into the workspace on every boot so they take effect
# even if OpenClaw recreates the workspace. We overwrite SOUL.md and AGENTS.md
# because they are operator config, not user state.
mkdir -p "$OPENCLAW_WORKSPACE"
cp "/opt/gaa/openclaw/SOUL.md" "$OPENCLAW_WORKSPACE/SOUL.md" 2>/dev/null || true
cp "/opt/gaa/openclaw/AGENTS.md" "$OPENCLAW_WORKSPACE/AGENTS.md" 2>/dev/null || true
# The front door client uses the same gateway token
export OPENCLAW_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-}"
# Front door (background) + OpenClaw gateway (foreground)
python3 -m uvicorn gaa.server.app:app --host 0.0.0.0 --port 8080 &
exec openclaw gateway run --bind lan
