# Sensor Tower — Browser-Proxy (Full + Guardrails) — Design

**Date:** 2026-06-16
**Status:** Design (approved in brainstorming; pending spec review → plan)
**Branch:** `feat/gaa-on-openclaw`
**Supersedes (on the prod agent path):** the runtime-side ST client/OAuth from
`2026-06-16-sensor-tower-mcp-design.md` — see "Relationship to the prior build".

## Goal

Give the GAA agent live Sensor Tower market data **despite the AgentBase runtime being
network-blocked from the connector**. The user's browser (on the VNG network) is an
allowed origin, so route every Sensor Tower call **through the browser**: the runtime
builds and budget-guards the query, the browser (which holds the user's O365 token and
can reach ST) executes it and returns the result.

## Context / why this design

Earlier we built a runtime-side ST integration (OAuth + MCP client in Python). A Phase-0
spike then found a hard blocker:

- From a **VNG-network machine**, ST returns **HTTP 401** (authenticate).
- From the **deployed AgentBase runtime**, the identical request returns **HTTP 403**
  (forbidden). Egress works (clean 0.34s response); the runtime's network origin is
  simply **not on the connector's allowlist**.
- **VPC mode does not reliably fix it** — AgentBase VPC mode routes only *private* CIDRs
  (`routeCidrs` rejects public ranges) for reaching private VPC resources; it does not
  reroute public egress. It would help only if ST had a private path (unknown; a
  network-team question). VPC/subnet discovery is also currently blocked (IAM SA lacks
  VServer perms).
- **CORS probe (decisive):** the connector returns `access-control-allow-origin: *` on
  both the MCP endpoint and `/token`, with a preflight allowing GET/POST/DELETE/OPTIONS
  and headers `Authorization, Content-Type, mcp-protocol-version, mcp-session-id`. So a
  **browser on the VNG network can run the entire ST flow itself** (OAuth + MCP) and read
  responses. Routing ST through the browser bypasses the 403 with **no connector-team or
  VPC action**.

Caveat: the 401-vs-403 is by **source IP**, so this works for users whose **browser is on
the VNG network** (office/VPN). Off-network browsers also 403. That matches the intended
VNG-internal audience.

## Sensor Tower tool surface (enumerated 2026-06-16 via O365 login)

Server "VNGGames Sensor Tower v2 - STG" v3.2.4 (FastMCP, MCP proto 2025-11-25). **6 tools,
all `readOnlyHint: true`**, 0 resources/prompts:

| Tool | Returns | Required args |
|---|---|---|
| `app_performance_api_v2_app_performance_get` | downloads, revenue, active users, retention, engagement | none* |
| `unified_app_performance_api_v2_unified_app_performance_g` | same, cross-platform unified | none* |
| `download_channel_api_v2_download_channel_get` | organic vs paid download attribution | none* |
| `app_store_api_v2_app_store_get` | ranks, ratings, reviews, review terms (daily only) | none* |
| `search_optimization_api_v2_search_optimization_get` | ASO: keyword rank/difficulty/visibility | none* |
| `fetch_report_api_v2_fetch_data_get` | retrieve a prior report by id | `report_id` |

Three design-shaping facts:
1. **Heavy, budget-metered schemas** — arrays of `countries/devices/bundles/metrics/app_id`
   from large controlled vocabularies; **every call deducts from a shared monthly
   "data-point" allowance** (3B/mo; `apps × countries × devices × date_count × bundles`;
   100k/bundle cap; 429 on overflow). Raw LLM-driven calls are error-prone and can burn the
   shared budget.
2. **Everything is ID-based — no find-app-by-name tool.** Callers must already know the ST
   `app_id`/`product_id`/`unified_app_id`. (\*The 5 data tools have no *required* field but
   are useless without an app/keyword.)
3. **All read-only** — safe to proxy.

## Decisions (from brainstorming)

1. **Browser-proxy** — the browser makes the ST calls; the runtime never touches ST.
2. **Full + guardrails** — expose the ST tools to the agent for on-demand use, but through a
   runtime wrapper that fills budget-minimal defaults, caps scope, and requires an
   app_id/keyword.
3. **App-IDs: ask-then-persist** — agent asks the user when an ID is missing, persists it on
   the active game profile for reuse.
4. **Relay = sidecar + the existing SSE activity-poller** (Approach 1).
5. **Per-user O365, conversational connect** (browser-side), single-active-session scope
   (concurrent multi-user is Phase 2).

## Architecture

**Three sides; the runtime is the brains, the browser is the muscle, ST is never touched by
the runtime.**

### Runtime (Python) — build, guard, relay

| Unit | Responsibility | Depends on |
|---|---|---|
| `gaa/mcp/tools.py` (changed) | Agent-facing **guarded** tools: `st_app_performance`, `st_unified_app_performance`, `st_download_channel`, `st_app_store`, `st_search_optimization` (defer `fetch_report`), plus `st_set_app_id`. Simplified schemas: required date range; `app_id`/`keyword` optional (resolved from profile or asked); optional `countries`, `metrics`. Routes to guard+relay. | `guard`, `relay`, profile |
| `gaa/sensortower/guard.py` (new) | Per tool: validate args, **resolve app_id** (arg → profile → `need_app_id`), **fill defaults** (devices/granularity/bundles/metrics), **estimate + cap** data points (trim scope), build the final ST request `{st_tool, params}`. | profile app-id store |
| `gaa/sensortower/relay.py` (new) | `request(built) → result`: write a *pending* sidecar `{req_id, st_tool, params}`, block-poll for a *result* sidecar (timeout ~120s), return result/timeout; enforce `req_id` correlation; clear sidecars on return. | `GAA_CACHE_DIR` sidecars |
| profile app-ID store | `get_app_ids(profile)` / `set_app_id(profile, label, id, id_type)` on the active game profile (mutating → vStorage snapshot). | ProfileStore |

### Front-door (Python) — bridge runtime ↔ browser

- Extend the **existing SSE activity-poller** (the one already narrating tool dead-air) to
  emit an `st_request` event `{req_id, st_tool, params}` when the pending sidecar appears.
- New bearer-gated `POST /sensor-tower/fulfill` `{req_id, result|error}` → writes the result
  sidecar (only for the current pending `req_id`; stale/duplicate ignored).

### Browser/frontend (TS) — OAuth + the actual ST call

- **ST OAuth** (PKCE public client): "Connect Sensor Tower" → `/authorize` → O365 →
  frontend `/sensor-tower/connected?code&state` → client-side token exchange (CORS `*`) →
  token in `sessionStorage` + refresh. `state` validated (CSRF).
- **ST executor**: on `st_request` → no token ⇒ fulfill `{not_connected}` + show Connect;
  else MCP streamable-HTTP call to ST with the bearer → fulfill `{result}` (or `{error}`).
- **Frontend relay route** `/api/sensor-tower/fulfill` → forwards to agent
  `/sensor-tower/fulfill` with `GAA_AGENT_TOKEN` (browser never holds it).

### Data flow (the relay)

```
LLM → st_app_performance(app_id?, start_date, end_date, …)
  guard: resolve app_id (arg→profile→need_app_id) · fill defaults · estimate+cap scope → built request
  relay: write pending sidecar {req_id, st_tool, params} ; block-poll result (≤120s)
front-door SSE poller: pending sidecar → emit st_request {req_id, st_tool, params}
browser: token? no → fulfill{not_connected}+Connect UI ; yes → MCP call ST → fulfill{result|error}
  /api/sensor-tower/fulfill → agent /sensor-tower/fulfill → write result sidecar (matching req_id)
relay poll resolves → tool returns to LLM
  (need_app_id → agent asks user + persists ; not_connected → agent says "click Connect", then RE-CALLS)
```

### Connect flow (browser-side, one-time per session)

```
"Connect Sensor Tower" → PKCE → ST /authorize → O365 login
  → frontend /sensor-tower/connected?code&state → client-side token exchange → store token → "connected"
```

## Guardrails (the point of "full + guardrails")

Cost = `apps × countries × devices × date_count × bundles`. The guard fills the scary params
budget-minimally and estimates+caps every query before relay.

**Defaults the guard fills (LLM supplies only app/keyword + dates + optional countries/metrics):**
- **apps = 1** (the single resolved ID; never auto-broadened).
- **countries** default `["US"]`; cap ≤ 5 (trim + note).
- **devices** `["ios-all","android-all"]` for app_performance/download_channel/app_store;
  `["all"]` for the unified tool (it requires one device).
- **granularity** default `monthly` (fewest date-points) unless asked; `app_store` is
  daily-only → daily with a tighter date cap.
- **date range** default last **90 days** if unspecified; hard-cap span at ST's 366 (trim + note).
- **bundles** one headline bundle per tool: `app_performance→download_revenue`,
  `unified→download_revenue`, `download_channel→download_channel`, `app_store→ranks`,
  `search_optimization→keywords` (caller may override/add).
- **metrics** default `[]` (= all in the chosen bundle; metrics don't affect budget); caller
  may narrow.

**Cap check:** estimate data points; if > a safe ceiling (**50,000**, well under the 100k/bundle
limit), trim in order (countries → date range → granularity) and return a `scope_trimmed` note.
A single over-broad query cannot drain the shared allowance.

## App-ID resolution + persistence (ask-then-persist)

- Active **game profile** gains an `app_ids` map: `{ label → {id, id_type} }`, e.g.
  `{"self": {"id": 12345, "id_type": "app_id"}, "competitor:clash": {"id": 67890, "id_type": "app_id"}}`.
- **Resolution order (guard):** explicit tool arg → profile lookup by the label the agent
  names → else `{status: "need_app_id", label}` so the agent asks the user.
- **`st_set_app_id(label, id, id_type?)`** persists to the active profile (snapshot). Data
  tools also accept a raw `app_id`; when the user supplies one with a label it's persisted.
- ID types: the four non-unified data tools take `app_id`/`product_id`; the unified tool takes
  `unified_app_id`. The guard maps the label's stored id to the correct ST param.

## Error contracts (all structured; ST is enrichment, never a hard dependency)

- `need_app_id` → agent asks the user (persists once given).
- `not_connected` → browser has no token → agent says "click Connect," then **re-calls** the
  tool after connect (clean retry; no mid-call pause/resume).
- `fulfill_timeout` → relay block-poll expired (~120s) → "Sensor Tower didn't respond in time;
  continuing without it."
- `upstream_error` → browser reported ST 4xx/5xx; **429 → "ST data-point budget exceeded."**
- `scope_trimmed` → not an error; a note on a successful result so the agent mentions what was
  narrowed.

## Security

- ST **token lives only in the browser** (sessionStorage); never sent to the runtime or logged
  — *more* secure than the prior runtime-side design.
- `GAA_AGENT_TOKEN` stays server-side: browser → frontend `/api/sensor-tower/fulfill` → agent
  `/sensor-tower/fulfill` (bearer). Browser never holds the agent token.
- PKCE + `state` on the browser OAuth (CSRF). The `st_request` SSE event carries only query
  params — no secrets.
- The budget guard doubles as an abuse control on the shared org allowance.
- `/sensor-tower/fulfill` is bearer-gated and `req_id`-correlated (stale results rejected).

## Testing

**Runtime (Python) — fully testable with the browser mocked** (tests write the result sidecar
to simulate the browser):
- `guard`: default-filling per tool, scope cap/trim + estimate math, app_id resolution order,
  id-type → ST-param mapping.
- `relay`: pending-sidecar write, result poll, timeout, `req_id` correlation, stale-fulfill ignored.
- profile app-id store: set/get round-trip + snapshot on set.
- `tools`: routing of `st_*` + `st_set_app_id`; pass-through of each error contract.
- front-door: SSE poller emits `st_request` when sidecar appears; `POST /sensor-tower/fulfill`
  (bearer gate, writes result sidecar, bad/stale `req_id` rejected).

**Frontend (TS):** OAuth flow (mock ST endpoints), ST executor maps `st_request`→fulfill (mock
ST MCP server/fetch), not-connected path, the `/api/sensor-tower/fulfill` relay route, the
connect-callback `state` validation.

**Acceptance — live smoke from a VNG-network browser:** a real `st_app_performance` result flows
end-to-end (browser OAuth → ST MCP → fulfill → agent tool result). No Phase-0 spike gate this time
(CORS `*` + laptop-origin-401 already prove the browser path).

## Relationship to the prior build

The prior spec/plan built a **runtime-side** ST path (`gaa/sensortower/{oauth,client,store}.py`,
the `sensor_tower_*` tools, `POST /sensor-tower/callback`, token persistence). Because the
runtime is 403-blocked, the prod path moves to the browser:
- **Superseded on the prod agent path:** `oauth.py`, `client.py`, `store.py`, the runtime token
  persistence, and the direct-call `sensor_tower_call/list_tools` tools. They are **retained**
  (still tested) and remain valid for a **local-laptop run mode** (where the runtime *is* on the
  VNG network and the 403 doesn't apply); they are not deleted.
- **Repointed:** the agent-facing ST tools now route through guard+relay (browser), not direct ST.
- **New work is mostly frontend (TS)** + `guard.py` + `relay.py` + the `st_request` SSE emission
  + `POST /sensor-tower/fulfill` + the profile app-id store.

## Out of scope (Phase 2+)

- Concurrent multi-user ST requests (single active request at a time today).
- `fetch_report` async-report retrieval (the long-running report pattern).
- A name→ID lookup (none exists in this connector).
- Off-VNG-network browser support (origin allowlist is IP-based).
- Retiring the dormant runtime-side Python ST modules.
