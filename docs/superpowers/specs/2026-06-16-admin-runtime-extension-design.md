# Admin Runtime Extension + Non-Admin Lockdown — Design

**Date:** 2026-06-16
**Status:** Design (approved in brainstorming; pending spec review → plan)
**Branch:** `feat/gaa-on-openclaw` (worktree `TestGreenNode-openclaw`)

## Goal

Give an authenticated **admin** (passphrase → cookie) full power over the running GAA
agent — including **registering new MCP servers at runtime** (e.g. a data crawler) and
**managing the secrets** those servers need — via the chat agent, while **non-admin**
users are restricted to analysis only. As part of the same build, **close a live
security hole**: the public non-admin agent currently has the full OpenClaw built-in
tool suite (`exec`, `read`, `write`, …) and can read any file / run any command.

## Context / Motivating finding (2026-06-16)

Probing the deployed v16 public frontend (`/api/chat`, no admin cookie) showed the
non-admin agent's tool list is:

```
read · write · edit · apply_patch · exec · process · canvas
dir_fetch · dir_list · file_fetch · file_write · sessions_spawn · gaa__*
```

It really read `/etc/os-release` and the rendered `openclaw.json` (not hallucinated).
So **any public visitor has RCE + arbitrary file read** (incl. `/proc/self/environ` →
all secrets). The only thing that blocked a direct secret dump was a *prompt-based*
refusal in the agent's persona — not a capability control, and trivially bypassable.

Root cause: `tools.deny: ["group:openclaw"]` in `render_config` does **not** remove the
dangerous tools. `group:openclaw` covers only a subset of built-ins (which is why
per-turn prompt tokens dropped ~half when it was added, yet `exec`/`read`/`write`
survived). **Deny-by-blocklist is unsafe** here; the fix is an **allow-list**.

## Decisions (locked in brainstorming)

1. **Admin power:** full raw — `exec`, `read`/`file_fetch`, `write`/`edit`/`apply_patch`,
   process/session tools, the `gaa__*` tools, and admin management tools. Blast radius
   (RCE + secret exfiltration if the passphrase leaks) is accepted by the owner.
2. **Admin surface:** chat-driven — the admin talks to the agent, which calls admin-gated
   management tools.
3. **Registered tools are shared** — a server an admin registers is available to non-admin
   analysis too (it extends analysis). Only the *management* of servers/secrets is
   admin-only.
4. **Secret rotation:** deferred (owner's call). Recommended once the lockdown ships.

## Architecture — two gateways, front door routes by `is_admin`

OpenClaw configures tool availability **globally per gateway** at boot, and the MCP
server's admin level is fixed at spawn. Per-request admin/non-admin tool sets therefore
require **two OpenClaw gateways in the one container**, with the front door routing each
`/chat` to the right one.

```
                  ┌ front door (:8080, FastAPI) — checks x-gaa-admin-key ┐
 browser ─► Vercel ─►                                                     │
                  │   is_admin == true  ──►  ADMIN gateway     (:18790)   │
                  │   is_admin == false ──►  NON-ADMIN gateway (:18789)   │
                  └──────────────────────────────────────────────────────┘

 NON-ADMIN gateway : tools allow-list = gaa__* + registered-server tools only
                     MCP server spawned with GAA_MCP_ADMIN=0  (no management tools)
 ADMIN gateway     : no tool restriction (full built-in suite: exec/read/write/…)
                     MCP server spawned with GAA_MCP_ADMIN=1  (management tools listed)
 Both gateways     : load every admin-registered MCP server (shared toolset)
 Shared, single-sourced: GAA_CACHE_DIR (gaa DB/runs), the registry + secret store,
                         the run/progress sidecars, and the persona workspace.
```

- **Non-admin = capability-denied** via allow-list (not prompt-denied). Built-in tools
  are absent from its config → closes the hole properly.
- **Admin** reached only with a valid `x-gaa-admin-key` (front door already computes
  `is_admin`; today's unused `is_admin` parameter in `stream_chat` becomes the router).
- Single-user demo, so routing per request is unambiguous (no concurrent admin +
  non-admin turns to reconcile).

## Components

### 1. `render_config(profile=…)` — `src/gaa/server/openclaw_config.py`
Add a `profile` parameter producing two variants:
- `profile="nonadmin"`: `tools.allow = ["gaa", <registered-server names/tool-ids>]`
  (exact allow-list syntax confirmed by Spike A); MCP `env` keeps `GAA_MCP_ADMIN=0`.
- `profile="admin"`: **no** `tools.deny`/`allow` restriction (full built-in suite); MCP
  `env` sets `GAA_MCP_ADMIN=1`.
- Both: merge each entry from the **MCP registry** into `mcp.servers`, with that server's
  `env` populated from the **secret store** (mechanism per Spike A/B).
- The existing `tools.deny: ["group:openclaw"]` is removed (proven ineffective).

### 2. Two gateways — `scripts/entrypoint.sh`
- Restore durable state once (registry, secret store, persona workspace, gaa cache).
- Render `openclaw.json` for each gateway into its own config dir (e.g.
  `~/.openclaw-nonadmin`, `~/.openclaw-admin`) with distinct ports (18789 / 18790).
- Launch both gateways + the front door (supervised). The gaa analysis state in
  `GAA_CACHE_DIR` and vStorage stays **single-sourced and shared**; the persona
  workspace is seeded/shared identically; `persist.py`'s snapshot target stays a single
  unambiguous directory (resolve exact layout in the plan — see Open Questions).

### 3. Front-door routing — `src/gaa/server/app.py` + `openclaw_client.py`
- `RealOpenClawClient` is constructed per gateway (admin URL, non-admin URL), or takes
  the target URL per call.
- `/chat` selects the client by `is_admin` (already computed from `x-gaa-admin-key`).
- Run/progress sidecars are shared, so activity narration + run-id surfacing are
  unchanged regardless of which gateway served the turn.

### 4. MCP registry + secret store — new module (e.g. `src/gaa/server/extensions.py`)
- **Registry** (JSON, vStorage-persisted): list of
  `{name, command, args, transport|url, env: {ENV_NAME: <secret-name>}}`.
- **Secret store** (JSON, vStorage-persisted, **separate file, mode 600**):
  `{secret-name: value}`. Never logged; listing returns names only.
- Both persisted to vStorage so they survive container restarts/redeploys (extend the
  `persist.py` durable set, or store inside the snapshotted workspace).

### 5. Admin management tools — `src/gaa/mcp/tools.py` + `src/gaa/server/actions.py`
New tools, added to `_SPECS`, registered in `ADMIN_ACTIONS` (and `MUTATING_ACTIONS`
where they change state) so existing gating applies (listed/callable only when the MCP
server runs with `GAA_MCP_ADMIN=1`, i.e. the admin gateway):
- `mcp_add(name, command|url, args?, env?)` — validate + append to registry → persist →
  trigger reload.
- `mcp_remove(name)` — remove from registry → persist → reload.
- `mcp_list()` — list registered servers (no secret values).
- `secret_set(name, value)` — upsert into the secret store → persist (→ reload if a
  registered server consumes it).
- `secret_unset(name)` — remove.
- `secret_list()` — **names only**.

### 6. Apply / reload
After a mutation: persist → re-render the affected gateway config(s) → reload so the new
server actually starts. Because registered tools are **shared**, a change reloads **both**
gateways. Reload mechanism per Spike B (hot-reload if OpenClaw supports it, else a
supervised gateway restart; the entrypoint already re-renders from the registry on boot,
so a restart applies cleanly — a few seconds' blip on config change is acceptable).

## Data flow — admin adds a crawler (happy path)
1. Admin unlocks (passphrase → `gaa_admin` cookie) → frontend sends `x-gaa-admin-key`.
2. Admin chats: "add a crawler MCP server `npx …`; it needs `CRAWLER_KEY=…`".
3. Front door routes to the **admin** gateway; the agent calls `secret_set("CRAWLER_KEY", …)`
   then `mcp_add(name="crawler", command="npx", args=[…], env={"CRAWLER_KEY":"CRAWLER_KEY"})`.
4. Tools persist registry + secret to vStorage and trigger a reload of both gateways.
5. After reload, the crawler's tools appear on both gateways; non-admin analysis can use them.

## Security model
- **Non-admin:** allow-listed to `gaa__*` + registered tools. No `exec`/`read`/`write`/
  session/process tools. Capability-enforced, not prompt-enforced. Verified by re-probe.
- **Admin:** full container control, gated solely by the passphrase. Accepted.
- **Secrets:** stored only in vStorage (mode 600 on disk), injected into the consuming
  server's env, never logged; `secret_list` returns names only.
- **Recommendation (deferred):** rotate LLM key, VSTORAGE keys, GAA tokens, and GreenNode
  IAM creds once the lockdown ships (they were reachable while the hole was open).

## Open questions / spikes (resolve before/early in the plan)
- **Spike A — tool restriction syntax:** the exact OpenClaw config that *actually* limits
  a gateway to a set of tools (since `deny:["group:openclaw"]` failed). Confirm an
  allow-list works by re-probing a locked-down gateway and seeing only `gaa__*`.
- **Spike B — MCP reload:** does OpenClaw hot-reload added MCP servers, or is a gateway
  restart required? Determines the apply mechanism + the supervisor design.
- **Spike C — two gateways + resources:** two gateways + two MCP servers + front door on
  the 2×4 flavor; confirm it fits or bump the flavor. Settle the config-dir / shared-
  workspace / single snapshot-target layout.

## Testing
- **Unit:** `render_config(profile="nonadmin")` → allow-list incl. registered tools, no
  built-ins, `GAA_MCP_ADMIN=0`; `render_config(profile="admin")` → no restriction,
  `GAA_MCP_ADMIN=1`, management tools present; registry merge; secret injection;
  management-tool validation + persistence; `secret_list` hides values.
- **Integration:** MCP `tool_specs(is_admin=True)` includes management tools;
  `is_admin=False` excludes them; `run_tool` rejects management tools when non-admin.
- **Live (post-deploy):** re-run the probe — non-admin shows **only** `gaa__*`
  (no `exec`/`read`/`write`); admin shows the full suite + management tools; add a test
  MCP server via admin chat → it appears and is callable from a non-admin turn.

## Out of scope
- A non-chat admin control panel (chat-driven only, per decision).
- Multi-user / concurrent admin+non-admin isolation beyond the single-user demo.
- Per-registered-tool admin-only scoping (registered tools are shared).
- Actually performing the secret rotation (separate, owner-driven follow-up).
