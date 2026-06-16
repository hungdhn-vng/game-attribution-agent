# Spike: OpenClaw tool-restriction, MCP reload, and two-gateway feasibility

Date: 2026-06-16
Image: `vcr.vngcloud.vn/111480-abp111723/gaa-custom-agent:v20260615-234137` (OpenClaw **2026.6.6**, bundled at `/app/openclaw.mjs`)
Method: pulled the image once, ran a long-lived container (`docker exec`), booted real `openclaw gateway run` instances, and verified the agent's actual tool surface via live `POST /v1/chat/completions` turns (the MaaS LLM at `LLM_BASE_URL` **was reachable** from this machine, so full chat-turn verification was possible) plus LLM-free introspection (`openclaw config schema`, `tools.catalog` / `tools.effective` RPC, the bundled `/app/docs/gateway/*` docs).

---

## GO / NO-GO: **GO**

All three spikes have clean, verified answers. The two-gateway + allow-list design is feasible. One surprise that **changes the plan** (see Spike C): `OPENCLAW_CONFIG_DIR` is **not** a recognized env var in this build — per-gateway isolation must use `OPENCLAW_CONFIG_PATH` (+ `OPENCLAW_STATE_DIR`) or `--profile`. The production entrypoint currently "works" only because it sets `OPENCLAW_CONFIG_DIR=/home/node/.openclaw`, which happens to equal the default config dir.

---

## Spike A — Correct tool-restriction syntax

### What the docs + schema say
- The top-level config key is **`tools`** (validated schema, `openclaw config schema`). Relevant sub-keys: `profile` (`minimal|coding|messaging|full`), `allow`, `alsoAllow`, `deny`, `byProvider`, `toolsBySender`.
- `tools.allow` is documented as: **"Absolute tool allowlist that replaces profile-derived defaults."** Rule of thumb from `/app/docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`: **"If `allow` is non-empty, everything else is treated as blocked."** and **"deny always wins."**
- Tokens are **case-insensitive and support `*` wildcards**. Entries may be: exact tool ids (`exec`), group ids (`group:fs`, `group:openclaw`, `group:plugins`), a plugin id (`bundle-mcp` = all OpenClaw-managed `mcp.servers`), or MCP server globs using the **provider-safe prefix** (`gaa__*`).
- `group:openclaw` is documented as "All built-in tools (**excludes provider plugins**)". The gaa MCP tools live under the `bundle-mcp` plugin id, **not** in `group:openclaw`. The four file-transfer tools (`dir_fetch`/`dir_list`/`file_fetch`/`file_write`) are a **plugin** (`plugin:file-transfer`), also not in `group:openclaw`.

### Why the current `deny: ["group:openclaw"]` fails (premise reproduced)
Booted a gateway with the **current** rendered config (`tools.deny: ["group:openclaw"]`) and asked the live agent to list its tools. Result — built-ins were **NOT** removed:
```
read write edit apply_patch exec process canvas
dir_fetch dir_list file_fetch file_write      <- plugin:file-transfer (never in group:openclaw)
gaa__analyze ... gaa__tools_show              <- 19 gaa tools (kept, good)
```
So `deny: ["group:openclaw"]` left `exec`/`read`/`write`/`edit`/`process` fully callable. In this build a `deny` of `group:openclaw` does not strip the core built-ins from the `/v1/chat/completions` agent surface, and by definition never touches plugin tools (`dir_*`, `file_*`). **Deny-by-group is the wrong tool for "only gaa".**

### Verified working configs (live chat-turn enumeration)
| Config `tools` block | Agent's actual tool surface |
| --- | --- |
| `{"allow": ["gaa__*"]}` | **ONLY** the gaa MCP tools (`gaa__analyze` … `gaa__tools_show`). No `read`/`write`/`exec`/`process`/`canvas`/`dir_*`/`file_*`. ✅ |
| `{"allow": ["bundle-mcp"]}` | Same — only the gaa MCP tools. ✅ (allows by plugin id; robust to MCP-prefix renaming) |
| *(key omitted entirely)* | **Full** built-in suite (`read write edit apply_patch exec process web_search web_fetch browser canvas nodes cron message gateway sessions_* subagents memory_* tts skill_workshop create_goal …`) **plus** the gaa tools. ✅ admin gateway |

Cross-checked the allow path with the server-side `tools.effective` RPC: under `allow:["gaa__*"]` it reports `profile: "full"` with `groups: []` (zero built-in groups survive the allowlist), confirming the model's self-report.

### Notes for the plan
- For the **gaa-only** gateway, prefer `{"allow": ["gaa__*"]}`. It is explicit and self-documenting. `{"allow": ["bundle-mcp"]}` is an equally-valid alternative that is immune to MCP-server-prefix changes (it allows whatever `mcp.servers` resolves to) — but it would also expose **any other** MCP server you add later, so `gaa__*` is the tighter choice for a single-purpose gateway.
- The MCP prefix is the provider-safe form of the `mcp.servers` key: for `mcp.servers.gaa` the glob is `gaa__*`. If the server key were renamed to something non-identifier-safe, the prefix could differ (chars → `-`, leading `mcp-`, possible truncation). Keeping the key `gaa` keeps the glob `gaa__*`.
- This also corrects the misleading comment in `src/gaa/server/openclaw_config.py` (it claims `deny:["group:openclaw"]` keeps the gaa tools while halving prompt tokens — the deny does keep gaa tools, but it does **not** remove the built-ins, so it is not a real restriction).

**RESULT (Spike A):**
- gaa-only gateway → `"tools": {"allow": ["gaa__*"]}` (absolute allowlist; verified the agent sees only the gaa MCP tools, no built-ins).
- admin gateway → omit the `tools` key entirely (or `"tools": {}`) → full built-in suite + gaa tools (verified).
- Form required: an **absolute `allow` list** (deny-by-group does not work). MCP tools are addressed by **server-prefix wildcard** `gaa__*` (or plugin id `bundle-mcp`); exact ids also work.

---

## Spike B — MCP server reload behavior

### Mechanisms found
1. **`openclaw mcp reload`** — CLI: *"Dispose cached MCP runtimes so new config is used on the next turn."* Targeted, deterministic; does not restart the gateway.
2. **Gateway config hot-reload** — the gateway watches the config file; `gateway.reload.mode` defaults to `"hybrid"` ("hot-apply safe changes, restart for critical ones"; also `hot`/`restart`/`off`). Invalid configs fail closed (reload skipped, gateway keeps running).

### Verified empirically (no gateway restart)
With a gateway already running (PID confirmed, ~2 min uptime), I added a second MCP server `gaa2` (a clone of `gaa`) to `mcp.servers`, then ran `openclaw mcp reload`:
```
Disposed cached MCP runtimes. Active agents use new MCP config on their next runtime build.
```
The **same** gateway process (unchanged PID) then served a fresh `/v1/chat/completions` turn and the agent now listed all 20 `gaa2__*` tools alongside the original `gaa__*` tools. So a newly-added `mcp.servers` entry is picked up **without restarting** the gateway — `mcp reload` disposes the cached MCP runtime and the next agent turn rebuilds it from the new config.

### Notes
- `mcp reload` only disposes MCP runtimes; the new server is read from the **active config file**, so write the updated `openclaw.json` first, then `mcp reload`.
- `mcp reload` operates on the gateway selected by `OPENCLAW_CONFIG_PATH`/`OPENCLAW_STATE_DIR` (or `--profile`/`--url`) — when running two gateways, target each one explicitly.
- A plain process restart of `openclaw gateway run` also picks up the new server (confirmed throughout the spike: every relaunch re-read the config), so "restart" remains a safe fallback if hot-reload is ever in doubt.

**RESULT (Spike B):** Hot-reload is supported. Use **`openclaw mcp reload`** (after writing the new `mcp.servers` entry into the gateway's `openclaw.json`) to load a new MCP server **without a gateway restart** — verified live (same PID, new `gaa2__*` tools on the next turn). The gateway also auto-hot-reloads safe config edits via `gateway.reload.mode:"hybrid"` (default). No SIGHUP needed.

---

## Spike C — Two gateways in one container + resources

### Feasibility: **YES** (verified two gateways live, on 18789 + 18790, in one container)

### SURPRISE / plan change: the config-dir env var
`OPENCLAW_CONFIG_DIR` (used today in `scripts/entrypoint.sh`) is **not a recognized variable** in this build. `openclaw config file` with `OPENCLAW_CONFIG_DIR=/home/node/.oc-gaa` still resolved to the default `~/.openclaw/openclaw.json`. The bundle only references `OPENCLAW_CONFIG_PATH`, `OPENCLAW_STATE_DIR`, `OPENCLAW_HOME` (grepped `/app/openclaw.mjs`). The current entrypoint "works" purely because it sets `OPENCLAW_CONFIG_DIR=/home/node/.openclaw` — the same path the default resolves to — so the file lands where OpenClaw already looks.

First two-gateway attempt (relying on `OPENCLAW_CONFIG_DIR`) **failed**: both gateways loaded the same default `~/.openclaw/openclaw.json`, so the "gaa-only" gateway showed the full built-in suite + leaked `gaa2__*`. After switching to the correct vars it worked perfectly.

### Correct per-gateway isolation (verified)
Run each gateway with its **own config file + own state dir + own port**:
```sh
# Admin gateway (full tools)
OPENCLAW_CONFIG_PATH=/home/node/.oc-admin/openclaw.json \
OPENCLAW_STATE_DIR=/home/node/state-admin \
  openclaw gateway run --bind lan --port 18789 --force

# gaa-only gateway (allow: ["gaa__*"])
OPENCLAW_CONFIG_PATH=/home/node/.oc-gaa/openclaw.json \
OPENCLAW_STATE_DIR=/home/node/state-gaa \
  openclaw gateway run --bind lan --port 18790 --force
```
- Port: `openclaw gateway run --port <n>` (flag, per `gateway --help`).
- Config file: `OPENCLAW_CONFIG_PATH=<abs path to openclaw.json>` (NOT `OPENCLAW_CONFIG_DIR`).
- State (agents/sessions/identity/logs): `OPENCLAW_STATE_DIR=<dir>` — give each gateway its own, otherwise they share the agent runtime/MCP-catalog state and the tool policy of one bleeds into the other (observed in the failed attempt).
- `--profile <name>` is the built-in shorthand (isolates `~/.openclaw-<name>/openclaw.json` + state); equivalent and simpler if you don't need explicit paths.

Verified surfaces after correct isolation:
- **Admin (18789):** 53 tools — full built-ins (`read write edit exec process browser canvas message gateway` …) + gaa tools, no `gaa2`.
- **gaa-only (18790):** exactly the gaa tools, **zero** built-ins, **zero** `gaa2`. Each gateway read only its own config.

### Shared workspace / state layout (recommended)
Agent **state** (`agents/<id>/sessions`, `identity`, `logs`) must be **per-gateway** (own `OPENCLAW_STATE_DIR`) — sharing it caused cross-contamination. The persona **workspace** (`SOUL.md`/`AGENTS.md`/`MEMORY.md`) and the **gaa data cache/DB** can and should be shared:
- `agents.defaults.workspace` is a real, schema-valid key — point **both** configs at one shared workspace dir (e.g. `/home/node/shared-workspace`) so the persona files are common. (Validated; both gateways accepted it.)
- The gaa MCP server already shares the gaa cache/DB via the `GAA_DB_PATH` / `GAA_CACHE_DIR` env it inherits — keep both gateways' `mcp.servers.gaa.env` pointed at the same `/home/node/.gaa/*`, so analysis state (onboarding, runs, sidecar) is shared regardless of which gateway invoked it.
- Keep **`openclaw.json` per gateway** (admin vs gaa-only differ only in the `tools` block) and **`OPENCLAW_STATE_DIR` per gateway**.

Recommended layout:
```
/home/node/.oc-admin/openclaw.json     # admin config (no tools key)      -> OPENCLAW_CONFIG_PATH
/home/node/.oc-gaa/openclaw.json       # gaa config  (allow: gaa__*)       -> OPENCLAW_CONFIG_PATH
/home/node/state-admin/                # admin agent/session/identity state -> OPENCLAW_STATE_DIR
/home/node/state-gaa/                  # gaa agent/session/identity state   -> OPENCLAW_STATE_DIR
/home/node/shared-workspace/           # SOUL/AGENTS/MEMORY (both configs' agents.defaults.workspace)
/home/node/.gaa/                       # shared gaa DB + cache + sidecar (both mcp.servers.gaa.env)
```
Note for `persist.py`: today it snapshots `OPENCLAW_CONFIG_DIR/workspace`. With this layout it should snapshot the **shared workspace** (`/home/node/shared-workspace`) and the shared `/home/node/.gaa` state instead — not a per-gateway state dir.

### Memory (real measurements, this image, under light concurrent load)
Snapshot with **2 gateways + front-door uvicorn + the gaa MCP children**, after firing one concurrent chat turn at each gateway:
- Container total (`docker stats`): **~1.46 GiB** (peak observed), ~19% of this host; CPU ~27% transient.
- Per-process RSS: each OpenClaw gateway node ≈ **365–410 MB**; front-door uvicorn ≈ **188 MB**; **each gateway spawns its own `gaa.mcp.server` child(ren) at ≈190 MB each** (so the gaa MCP server memory is paid **per gateway**, ~190–380 MB × 2).
- Sum of workload RSS ≈ **1.7–1.8 GB**.

Fits a **2 CPU / 4 GB** flavor (peak ≈1.5 GiB ≈ 37% of 4 GB). Caveat: this was a trivial "hello/list tools" load; a real `gaa analyze` turn loads heavier Python (pandas/data) inside the gaa MCP process, and running the gaa MCP server in **both** gateways doubles that cost. Headroom on 4 GB is adequate but not generous. If analyze workloads run concurrently on both gateways, watch RSS or bump to the next flavor; a cheaper mitigation is to keep the gaa MCP server only on the gateway(s) that actually need it (e.g. don't wire `mcp.servers.gaa` into the admin config unless the admin gateway needs gaa tools).

**RESULT (Spike C):** Feasible — two `openclaw gateway run` processes in one container, verified on ports 18789/18790 with correctly isolated tool surfaces. Per-gateway config = **`OPENCLAW_CONFIG_PATH=<file>`** (NOT `OPENCLAW_CONFIG_DIR`), per-gateway state = **`OPENCLAW_STATE_DIR=<dir>`**, port = **`--port <n>`** (or use `--profile <name>` for both at once). Share the persona workspace via `agents.defaults.workspace` and the gaa cache/DB via `mcp.servers.gaa.env`; keep `openclaw.json` and state dirs per-gateway. Peak memory ≈ **1.5 GiB** under light load → **fits 2 CPU / 4 GB** (each gateway pays ~190 MB+ for its own gaa MCP child, so monitor under real analyze load).

---

## Surprises that should change the plan
1. **`OPENCLAW_CONFIG_DIR` is not a real knob.** Use `OPENCLAW_CONFIG_PATH` (+ `OPENCLAW_STATE_DIR`) or `--profile`. The current single-gateway entrypoint survives only because its value equals the default dir; a second gateway pointed via `OPENCLAW_CONFIG_DIR` silently reuses the default config (this caused the first two-gateway attempt to fail).
2. **`deny: ["group:openclaw"]` is not a restriction.** It leaves `exec`/`read`/`write`/`edit`/`process` callable and by design never touches plugin tools (`dir_*`/`file_*`). Switch the gaa surface to `allow: ["gaa__*"]`. The "~halves prompt tokens" comment in `openclaw_config.py` should be re-measured under `allow` (an allowlist that drops all built-ins should reduce tokens at least as much).
3. **The gaa MCP server runs once per gateway.** Two gateways = two gaa MCP child processes = double the gaa MCP memory. Only wire `mcp.servers.gaa` into a gateway that needs gaa tools.
4. **State sharing causes tool-policy bleed.** Two gateways sharing one `OPENCLAW_STATE_DIR` cross-contaminate (the failed attempt showed the gaa-only gateway exposing full built-ins + the other gateway's `gaa2`). State dirs must be per-gateway; only the workspace + gaa cache are safe to share.
