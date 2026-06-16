#!/usr/bin/env sh
set -eu
WS="${OPENCLAW_WORKSPACE:-/home/node/.openclaw/workspace}"
NA_CFG="${OPENCLAW_CONFIG_NONADMIN:-/home/node/.openclaw-nonadmin/openclaw.json}"
NA_STATE="${OPENCLAW_STATE_NONADMIN:-/home/node/.openclaw-nonadmin/state}"
AD_CFG="${OPENCLAW_CONFIG_ADMIN:-/home/node/.openclaw-admin/openclaw.json}"
AD_STATE="${OPENCLAW_STATE_ADMIN:-/home/node/.openclaw-admin/state}"

# 1. Ensure directories exist before restore
mkdir -p "$WS" "$(dirname "$NA_CFG")" "$NA_STATE" "$(dirname "$AD_CFG")" "$AD_STATE" "$GAA_CACHE_DIR"

# Sidecar paths shared between the front-door and the MCP server (via openclaw.json env refs)
export GAA_ST_REQUEST="${GAA_ST_REQUEST:-$GAA_CACHE_DIR/sensortower/st_request.json}"
export GAA_ST_RESULT="${GAA_ST_RESULT:-$GAA_CACHE_DIR/sensortower/st_result.json}"

# 2. Restore durable state FIRST (workspace + registry + secrets; no-op if VSTORAGE_* unset)
python3 -m gaa.persist restore || true

# 3. Render per-profile configs (always fresh, NOT snapshotted)
render() {
  python3 -c "import os; from gaa.server.openclaw_config import render_config; \
print(render_config(model=os.environ.get('LLM_MODEL','google/gemma-4-31b-it'), profile='$1'))" > "$2"
}
render nonadmin "$NA_CFG"
render admin    "$AD_CFG"
chmod 0600 "$NA_CFG" "$AD_CFG" 2>/dev/null || true

# 4. Seed workspace persona files ONLY if absent (restore may have placed evolved versions)
[ -f "$WS/SOUL.md" ]   || cp /opt/gaa/openclaw/SOUL.md   "$WS/SOUL.md"   2>/dev/null || true
[ -f "$WS/AGENTS.md" ] || cp /opt/gaa/openclaw/AGENTS.md "$WS/AGENTS.md" 2>/dev/null || true
[ -f "$WS/MEMORY.md" ] || cp /opt/gaa/openclaw/MEMORY.md "$WS/MEMORY.md" 2>/dev/null || true

# 5. The front door client uses the same gateway token
export OPENCLAW_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-}"

# 6. Front door (background) + both OpenClaw gateways (background)
python3 -m uvicorn gaa.server.app:app --host 0.0.0.0 --port 8080 &
OPENCLAW_CONFIG_PATH="$NA_CFG" OPENCLAW_STATE_DIR="$NA_STATE" openclaw gateway run --bind lan --port 18789 &
OPENCLAW_CONFIG_PATH="$AD_CFG" OPENCLAW_STATE_DIR="$AD_STATE" openclaw gateway run --bind lan --port 18790 &

# 7. Reload loop: watch the flag (written by request_reload), re-render configs,
#    then hot-reload each gateway's MCP servers WITHOUT a gateway restart (Spike B).
FLAG="$GAA_CACHE_DIR/extensions/reload.flag"
while true; do
  sleep 3
  if [ -f "$FLAG" ]; then
    rm -f "$FLAG"
    render nonadmin "$NA_CFG" || { echo "render nonadmin failed; skipping reload" >&2; continue; }
    render admin    "$AD_CFG" || { echo "render admin failed; skipping reload" >&2; continue; }
    chmod 0600 "$NA_CFG" "$AD_CFG" 2>/dev/null || true
    OPENCLAW_CONFIG_PATH="$NA_CFG" OPENCLAW_STATE_DIR="$NA_STATE" openclaw mcp reload || true
    OPENCLAW_CONFIG_PATH="$AD_CFG" OPENCLAW_STATE_DIR="$AD_STATE" openclaw mcp reload || true
  fi
done
