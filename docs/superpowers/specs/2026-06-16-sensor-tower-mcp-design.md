# Sensor Tower MCP — Conversational Connect & Proxy — Design

**Date:** 2026-06-16
**Status:** Design (approved in brainstorming; pending spec review → plan)
**Branch:** `feat/gaa-on-openclaw` (worktree `TestGreenNode-openclaw`)

## Goal

Make the GAA agent **robust on real market data** by giving it access to **Sensor
Tower** through an MCP connector. The agent walks the user through connecting their
own **VNG O365** account mid-chat (self-service OAuth), then proxies Sensor Tower's
MCP tools so the model can pull live market/competitor data on demand. Later, the
high-value Sensor Tower signals get baked into the deterministic analysis engine.

## Context / Findings (2026-06-16)

A test harness exists at `../Random/TestMCP/test_mcp.py` (OAuth + tool-listing probe).
Recon against the live connector established:

- **Server:** `https://stg-aawp-connector.vnggames.net/sensor-tower-v2` — an
  "aawp-connector" gateway fronting Sensor Tower, **staging** tier, MCP over
  **streamable HTTP**.
- **Reachability:** resolves to a *public* IP (`116.118.91.93`) and returns a clean
  `401` from a dev machine — internet-facing, not strictly VNG-LAN-only. Whether a
  **PUBLIC AgentBase runtime** can reach it is **unverified** (possible IP allowlist).
- **Auth (the crux):** OAuth 2.1 over O365. Authorization-server metadata
  (`/.well-known/oauth-authorization-server/sensor-tower-v2`) reports:
  - `grant_types_supported: ["authorization_code", "refresh_token"]` — **no
    `client_credentials`** → a headless agent **cannot** self-authenticate; a human
    must complete the interactive O365 login at least once, after which the
    `refresh_token` keeps the session alive.
  - `code_challenge_methods_supported: ["S256"]` (PKCE), `registration_endpoint`
    present (**Dynamic Client Registration**), `scopes_supported: ["openid"]`,
    `token_endpoint_auth_methods_supported: ["client_secret_post","client_secret_basic"]`,
    `authorization_endpoint`/`token_endpoint` under the `/sensor-tower-v2` path.

Agent-side facts that shape the design:

- **Single-tenant today.** `/chat` and `/upload` are gated by one shared
  `GAA_AGENT_TOKEN` the Vercel frontend holds for *all* users; there is no
  per-end-user identity anywhere, and state is global ("single-user-demo").
- **OpenClaw MCP wiring is static per-process.** `openclaw_config.render_config`
  emits `mcp.servers` once at boot; it **cannot** swap a per-user bearer token per
  request. So Sensor Tower **cannot** be a normal OpenClaw `mcp.servers` entry, and
  the AgentBase Resource Gateway's 3LO (which keys tokens off the *inbound* identity)
  hits the same wall — OpenClaw sends one shared identity it can't vary per request.
- **The `gaa` MCP server is the right host.** It is an in-process MCP `Server`
  (`src/gaa/mcp/server.py`) with async `list_tools`/`call_tool` delegating to a
  **sync** `tools.run_tool` over a `_SPECS` registry (`src/gaa/mcp/tools.py`). It can
  itself be an MCP *client* of Sensor Tower and re-expose ST tools.
- **`market` and `signals` tools already exist** in `_SPECS` ("Genre/market benchmark
  comparison", "Competitor signals") — backed by local/synthetic data today. These
  are the natural homes for the later enrichment phase.

## Decisions (from brainstorming)

1. **Usage model:** per-user — each end-user uses their own O365 token (an org
   access/audit requirement; the ST *data* is the same regardless of who asks).
2. **Sequencing:** **stage it** — prove data value first; full concurrency-safe
   multi-tenancy is deferred to Phase 2.
3. **Integration surface:** **proxy now, enrich next** — Phase 1a re-exposes ST's MCP
   tools on demand (tool-agnostic; also *discovers* the tool surface); Phase 1b backs
   `market`/`signals` with real ST data.
4. **Auth UX:** the agent **instructs the user to connect mid-chat** (self-service),
   reusing the OAuth approach from `test_mcp.py`.
5. **Callback UX:** **web callback (polished)** — a Vercel `/sensor-tower/callback`
   route catches the browser redirect and relays the code to the agent; no copy-paste.

## Approach chosen (and rejected alternatives)

**Chosen — ST client embedded in the `gaa` MCP server, with conversational connect.**
The `gaa` server becomes an MCP *client* of Sensor Tower. New connect/status/complete
tools let the agent drive a per-user OAuth flow; proxied `st__*` tools forward calls
with the connected session's token. Fits the existing architecture, reuses the secret
store + vStorage persistence + the `test_mcp.py` OAuth knowledge, and seeds Phase 1b.

**Rejected — OpenClaw native remote MCP entry** (`mcp.servers` `url` + static bearer):
OpenClaw's config is static with no place to *refresh* an OAuth token; ST access
tokens expire (~hourly) and there is no `client_credentials` grant, so a static bearer
dies fast. The `url` entry has no auth-header slot today either.

**Deferred to Phase 2 — AgentBase Resource Gateway with 3LO.** Platform-native,
per-user-friendly (managed token storage + refresh + policy), but 3LO keys tokens off
the *inbound* identity and OpenClaw sends one shared identity it can't vary per
request. Overkill for Phase 1's single active session; revisit when building genuine
multi-tenancy.

## Architecture

### New module: `gaa/sensortower/` (framework-free)

| Unit | Responsibility | Depends on |
|---|---|---|
| `oauth.py` | OAuth 2.1 dance by hand (the SDK's inline flow blocks one connection; our login spans chat turns): `register_client()` (DCR `POST /register`), `build_authorize_url(session)` → `(url, state)`, `exchange_code(code, state)` → tokens, `refresh(tokens)`. Endpoints from discovery metadata. | `httpx`, `store` |
| `store.py` | Per-session token store + pending-connect store; JSON under `GAA_CACHE_DIR` (snapshotted to vStorage), mode `0600`. `session → {tokens, expiry}`; `state → {code_verifier, session, ts}` with short TTL; app-level DCR `client_creds`. | `gaa.persist` |
| `client.py` | The ST **MCP client**: given a session's valid token, opens a `streamablehttp_client` session to `/sensor-tower-v2`, lists tools (cached), forwards `call_tool`. Runs on a background asyncio loop in a thread; sync `run_tool` bridges via `run_coroutine_threadsafe`. `401 → refresh → retry once`. | `mcp` SDK, `oauth`, `store` |

**Boundary check:** `oauth` knows the protocol but nothing about MCP; `client` knows
MCP but delegates all token logic to `oauth`/`store`; `tools.py` only routes. Each is
independently testable.

### Changed (surgical)

- **`gaa/mcp/tools.py`** — add **two** agent-facing tools `sensor_tower_status` /
  `sensor_tower_connect` to `_SPECS`; `tool_specs()` appends discovered `st__*`
  proxied tools (schemas mirrored verbatim from ST); `run_tool()` routes
  `sensor_tower_*` + `st__*` into `gaa.sensortower`. **Completion is *not* a chat
  tool** in the web-callback design — `oauth.exchange_code` is invoked server-side by
  the callback endpoint; the agent detects success by polling `sensor_tower_status`.
- **`gaa/server/app.py`** — add bearer-gated `POST /sensor-tower/callback`, called
  **server-to-server by the frontend** (never the browser) → `oauth.exchange_code` →
  store tokens under the session.
- **Frontend** — Next.js server route `/sensor-tower/callback`: catch the browser
  redirect, relay `{code, state}` to the agent with the existing `GAA_AGENT_TOKEN`,
  render "✅ connected — return to chat."
- **Agent SOUL** — the playbook: *needs market data → `sensor_tower_status` → if not
  connected, `connect`, show the link, ask them to finish → (callback completes) → use
  `st__*`.*

### Connect data flow

```
chat ──▶ agent calls sensor_tower_connect
          └─▶ gaa: DCR register (once) + PKCE + state=session → returns authorize URL
     ◀── agent shows the login link to the user
user ──▶ logs in with O365
          └─▶ ST redirects browser to  https://<frontend>/sensor-tower/callback?code&state
frontend (server route) ──▶ POST /sensor-tower/callback {code,state} + agent token ──▶ agent
          └─▶ oauth.exchange_code → store tokens under session ; render "connected"
user ──▶ back in chat, asks for data ──▶ agent calls st__<tool>
          └─▶ client forwards with the session token (auto-refresh) ──▶ ST data ──▶ analysis
```

## Token lifecycle & refresh

- **DCR client — once, app-level.** Register one client (`redirect_uri` = prod Vercel
  callback, `grant_types: [authorization_code, refresh_token]`, `response_types:
  [code]`, `token_endpoint_auth_method: client_secret_post`). `client_id`/`client_secret`
  identify our *app* (not a user) → persist durably and reuse for every connect;
  re-register only if missing or `client_secret_expires_at` passed.
- **Per-connect:** `connect` generates PKCE `code_verifier` + `S256` challenge + random
  `state`, stashes `{state → (verifier, session, ts)}` (~10-min TTL), builds the
  `/authorize` URL (`scope=openid`). `exchange_code` validates state (pending,
  unexpired, single-use), `POST /token` (`grant_type=authorization_code`), stores
  `{access_token, refresh_token}` with `expiry = now + expires_in − 60s`, deletes the
  pending state.
- **Refresh — proactive + reactive.** Before any `st__*` call, if `now ≥ expiry`,
  refresh; if a call still returns `401`, refresh once and retry. Store a rotated
  `refresh_token` if returned. If refresh fails (expired/revoked) → mark session
  disconnected → `st__*` returns `not_connected` so the agent re-prompts connect.
- **Persistence:** tokens, client creds, and pending states live in
  `gaa/sensortower/store.py` under `GAA_CACHE_DIR`, snapshotted to vStorage on
  mutation → a container restart keeps a connected session alive.

## Security

- Secrets never cross the wrong boundary: `POST /sensor-tower/callback` is bearer-gated
  and server-to-server only; the browser never sees `GAA_AGENT_TOKEN`; tokens/`code`
  never enter the chat transcript or logs. `sensor_tower_status` returns only
  `{connected, expires_in}` — never the token.
- CSRF/replay: `state` random, single-use, TTL-bounded; PKCE S256; `redirect_uri`
  exact-match (fixed at DCR).
- Token-at-rest: store `0600`, values never logged; DCR `client_secret` same grade.
- Tool namespacing: proxied tools prefixed `st__`; ST input schemas mirrored verbatim.

## Error handling

All failures are returned as **structured tool results**, never exceptions to the user;
ST is *enrichment*, never a hard dependency (analysis must still run with ST absent):

- `not_connected` → agent runs the connect playbook.
- `upstream_error` (ST 5xx / rate-limit / timeout) → agent reports "Sensor Tower
  unavailable, proceeding without it."
- `bad_args` → schema validation message.

## Concurrency caveat (Phase 1 scope)

Token selection at `st__*`-call time keys off the session, but the `gaa` MCP server is
a single shared stdio process — so Phase 1 is **single-active-session safe**;
simultaneous distinct users are **Phase 2**. The `state` correlation and per-session
storage are built now so Phase 2 only has to thread real per-session identity through
the call path.

## Testing

**Phase 0 — de-risk spike (reuses `test_mcp.py`), before building:**
1. Confirm the **PUBLIC AgentBase runtime can reach** `stg-aawp-connector.vnggames.net`
   (probe from inside the deployed container; if blocked → VPC mode, learned now).
2. Confirm **DCR accepts an `https` Vercel `redirect_uri`** (`test_mcp.py` only proved
   `localhost`).
3. **Enumerate ST's tools + schemas** (one O365 login) → designs Phase 1b and validates
   `st__*` naming.

**Unit (TDD, matching repo discipline):**
- `oauth.py` — mock `httpx`: register / authorize-URL / exchange / refresh + rotation /
  state validation / expiry math.
- `store.py` — round-trip, TTL expiry of pending state, `0600`, snapshot hook fires.
- `client.py` — against a fake in-process MCP server: list + forward, `401 → refresh →
  retry`, `not_connected` path.
- `tools.py` — routing of `sensor_tower_*` + `st__*`, namespacing, ST-absent fallthrough.
- `app.py` — callback endpoint: bearer gate, happy relay, bad/expired state.
- Frontend — callback route relays + renders.

**Live (gated/manual, needs O365):** one end-to-end test against real ST staging with a
captured token — list tools, call one.

## Deploy deltas

- New config/env: ST base URL (`GAA_ST_BASE_URL` or similar) + prod callback URL.
- Redeploy `gaa-custom-agent`; frontend gains `/sensor-tower/callback` + redeploy.
- `redirect_uri` registered via DCR must exactly match the prod Vercel callback.

## Out of scope (Phase 2+)

- Concurrency-safe per-user token selection across simultaneous users (true
  multi-tenancy: per-session identity threaded through `/chat` → OpenClaw → `gaa`).
- **Phase 1b enrichment:** backing `market`/`signals` with real ST signals (separate
  follow-on once the Phase-0 spike reveals the tool surface).
- AgentBase Resource Gateway 3LO migration.
