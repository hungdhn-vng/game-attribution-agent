#!/usr/bin/env sh
set -eu
# OPENCLAW_CONFIG_DIR is the ~/.openclaw directory where openclaw.json lives.
# (Do NOT use OPENCLAW_HOME — OpenClaw treats that as the parent of ~/.openclaw,
#  which would double the path and break config loading.)
OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/home/node/.openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_CONFIG_DIR}/workspace"
# 1. Ensure directories exist before restore (restore writes into them)
mkdir -p "$OPENCLAW_CONFIG_DIR" "$OPENCLAW_WORKSPACE" "$GAA_CACHE_DIR"
# 2. Restore durable state FIRST (workspace-only; no-op if VSTORAGE_* unset)
python3 -m gaa.persist restore || true
# 3. Render the OpenClaw config each boot (idempotent; NOT snapshotted — always fresh)
python3 -c "import os; from gaa.server.openclaw_config import render_config; print(render_config(model=os.environ.get('LLM_MODEL','google/gemma-4-31b-it')))" > "$OPENCLAW_CONFIG_DIR/openclaw.json"
# 4. Seed workspace persona files ONLY if absent (restore may have placed evolved versions)
[ -f "$OPENCLAW_WORKSPACE/SOUL.md" ] || cp "/opt/gaa/openclaw/SOUL.md" "$OPENCLAW_WORKSPACE/SOUL.md" 2>/dev/null || true
[ -f "$OPENCLAW_WORKSPACE/AGENTS.md" ] || cp "/opt/gaa/openclaw/AGENTS.md" "$OPENCLAW_WORKSPACE/AGENTS.md" 2>/dev/null || true
[ -f "$OPENCLAW_WORKSPACE/MEMORY.md" ] || cp "/opt/gaa/openclaw/MEMORY.md" "$OPENCLAW_WORKSPACE/MEMORY.md" 2>/dev/null || true
# 5. The front door client uses the same gateway token
export OPENCLAW_TOKEN="${OPENCLAW_GATEWAY_TOKEN}"
# 6. Front door (background) + OpenClaw gateway (foreground)
python3 -m uvicorn gaa.server.app:app --host 0.0.0.0 --port 8080 &
exec openclaw gateway run --bind lan
