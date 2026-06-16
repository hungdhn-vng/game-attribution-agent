# Notion MCP — Build Updates & User Sentiment Connector — Design

**Date:** 2026-06-16
**Status:** Design approved → in implementation (worktree `feat/notion-mcp`).
**Branch:** `feat/notion-mcp` (worktree `TestGreenNode-notion-mcp`)

> **⚠️ Read the "Live recon corrections (2026-06-16)" section at the bottom first.**
> A live probe of the user's real Notion workspace changed the API model: it uses
> Notion's **new data-source model** (`Notion-Version: 2025-09-03`, query via
> `/v1/data_sources/{id}/query`), **not** the `2022-06-28` `/databases/{id}/query`
> model the body below originally assumed. Where the body and the corrections differ,
> **the corrections win** and the implementation plan reflects them.

## Goal

Give the GAA agent access to **Notion** so it can pull qualitative context — primarily
**build/release updates** and **user sentiment**, with a generic escape hatch for
anything else in the workspace. Two consumption modes:

1. **Enrich attributions** — after a `gaa__analyze` over a date window, the agent pulls
   build updates + sentiment for that same window and weaves the "why" into its
   narrative (the deterministic engine finds *what* changed; Notion supplies *why*).
2. **Standalone Q&A** — the user asks the agent directly ("what shipped last week?",
   "how's sentiment trending?") and it answers from Notion.

…while retaining **generic Notion read access** (search/fetch) for ad-hoc questions the
two focused tools don't cover.

## Context / Findings (2026-06-16)

Established from the current codebase:

- **A runtime-extension mechanism already exists.** In admin mode the agent can
  `mcp_add` (register an MCP server by `command`+`args` or `url`), `secret_set` (store a
  secret), and a supervised reload re-renders `openclaw.json`
  (`src/gaa/server/openclaw_config.py`) to wire the server in. Registered servers come
  from `gaa.server.extensions.list_servers()`; their `env` map (`{ENV_VAR → secret_name}`)
  is resolved against the secret store at render time
  (`openclaw_config.render_config` lines 68–79). **Connecting an MCP server therefore
  needs no `render_config` change and no redeploy** — only the runnable code must exist
  in the image.
- **Non-admin allowlisting is automatic.** `render_config` appends `"{name}__*"` to
  `tools.allow` for every registered server (line 84), so once `notion` is registered
  its tools are reachable in non-admin mode too.
- **Secret store fits a static token.** `extensions.set_secret/get_secret` is a generic
  `0600` JSON KV under `GAA_CACHE_DIR`, snapshotted to vStorage, names-only listing,
  values never logged. Notion's single-workspace **internal integration token** maps
  directly onto it (no OAuth needed).
- **The `gaa` MCP server is a clean template.** `src/gaa/mcp/server.py` is a stdio MCP
  `Server` with `list_tools`/`call_tool` delegating to a sync `tools.run_tool` over a
  `_SPECS` registry returning compact `{status, …}` dicts as `TextContent`
  (`src/gaa/mcp/tools.py`). We mirror this shape.
- **`httpx>=0.28.1` is a core dependency**; `mcp>=1.27` is in the `server` extra. A new
  `gaa.notion` submodule is picked up by the existing `[tool.setuptools.packages.find]`
  (`where = ["src"]`) — **no `pyproject` change, no new pip package** — and runs as
  `python -m gaa.notion.server`.

## Why this differs from the Sensor Tower MCP (`2026-06-16-sensor-tower-mcp-design.md`)

Sensor Tower is **embedded inside the `gaa` MCP server** because each end-user uses
their **own O365 OAuth token**, which must be swapped per request and refreshed
(~hourly) — something OpenClaw's static `mcp.servers` wiring cannot do.

Notion is the opposite: **one static workspace integration token, shared for all
requests**. There is nothing to vary per request and nothing to refresh, so a normal
`mcp.servers`-style entry works perfectly. That makes the simpler, **decoupled**
design available: a standalone `gaa.notion` server, registered at runtime via the
existing admin `mcp_add` path, with the token injected as a static env var. It never
imports `gaa.core` and `gaa.core` never imports it.

## Decisions (from brainstorming)

1. **Purpose:** enrich attributions **and** standalone Q&A, **plus** retain generic
   Notion access as an escape hatch → a layered tool surface (focused tools over generic
   primitives).
2. **Notion data shape:** unknown / mixed → tools resolve flexibly (structured DB query
   when a database is configured, keyword-search fallback otherwise).
3. **Hosting / wiring:** **runtime-register via admin** — ship `gaa.notion` as a runnable
   module; connect on demand with `secret_set` + `mcp_add`. No `render_config` change.
4. **Auth:** Notion **internal integration token** via the existing secret store (single
   workspace; no OAuth).
5. **Scope:** **read-only** — no create/update/delete (YAGNI; can extend later).
6. **Enrichment coupling:** **agent-orchestrated**, not a code hook into the pipeline
   (the agent calls both tool sets and combines). SOUL.md guidance is an optional
   follow-up, not part of the core server build.

## Approach chosen (and rejected alternatives)

**Chosen — standalone `gaa.notion` stdio MCP server, runtime-registered via admin.**
Self-contained module exposing four read-only tools. Connected once via
`secret_set notion_token …` + `mcp_add name=notion command=python3
args=["-m","gaa.notion.server"] env={…}`; the secret store injects the token (and
optional DB ids) as env. Maximally decoupled, reuses the entire existing extension +
secret + allowlist machinery, no `render_config` or `pyproject` change.

**Rejected — embed in the `gaa` MCP server (the Sensor Tower pattern).** Justified there
by per-user OAuth token swapping; unnecessary here (static token) and it would couple an
unrelated data source into the analysis server. Keep boundaries clean.

**Rejected — wire Notion's official hosted MCP** (generic `url` entry via `mcp_add`).
Already *possible* today with zero new code, but its large generic tool surface bloats
the prompt for the weak MaaS model (contra the project's tool-trimming discipline) and
isn't shaped to build-updates/sentiment. The focused tools are the point; generic access
is preserved via our own `notion_search`/`notion_fetch`.

**Rejected — baked-in stdio entry in `render_config` (the `gaa` pattern).** First-class
and always-present, but requires editing `render_config` and a redeploy to ship/change;
the runtime-register path gives connect/disconnect/rotate with no redeploy.

## Architecture

### New module: `gaa/notion/` (framework-free, no `gaa.core` dependency)

| Unit | Responsibility | Depends on |
|---|---|---|
| `client.py` | Thin Notion REST client over `httpx`: `search(query, type?, limit)`, `query_database(db_id, since?, until?, limit)`, `get_page(id)`, `get_block_children(id)`. Base `https://api.notion.com/v1`, headers `Authorization: Bearer <token>` + `Notion-Version: 2022-06-28`. Reads `NOTION_TOKEN` from env; surfaces HTTP status. No retries beyond surfacing `429 retry_after`. | `httpx` |
| `tools.py` | The four tool `_SPECS` (name/description/JSON-schema), `tool_specs()`, and `run_tool(name, args)`: validates args (`jsonschema`), resolves source (structured vs. search), shapes compact results, returns `{status, …}` dicts. Best-effort Notion property detection + result truncation/caps live here. | `client`, `jsonschema` |
| `server.py` | stdio MCP adapter mirroring `gaa/mcp/server.py`: `build_server()` with `list_tools`/`call_tool` → `tools.run_tool`; `main()` runs `stdio_server`. Entry: `python -m gaa.notion.server`. | `mcp`, `tools` |

**Boundary check:** `client` knows HTTP/Notion but nothing about tool shaping; `tools`
shapes results but delegates all I/O to `client`; `server` only adapts to MCP. Each is
independently testable, and the whole module is independently runnable.

### Tool surface (4 tools, lean for the MaaS model)

| Tool | Purpose | Args | Returns (compact) |
|---|---|---|---|
| `build_updates` | Recent build/release/patch notes | `since?`, `until?`, `query?`, `limit?` (default ~10) | `[{version?, date, title, summary, url}]` |
| `user_sentiment` | Player feedback / sentiment items | `since?`, `until?`, `query?`, `limit?` | `[{date, source?, snippet, url}]` (raw items, **not** scored/aggregated) |
| `notion_search` | Generic escape hatch | `query` (required), `type?` (`page`\|`database`), `limit?` | `[{title, type, url, id}]` |
| `notion_fetch` | Read a page/db by id-or-url | `id` (required) | page text (markdown-ish, truncated) **or** db rows |

`build_updates`/`user_sentiment` are the enrichment + Q&A workhorses; `notion_search`/
`notion_fetch` cover anything else. All results truncated/capped to protect the token
budget (long rich-text clipped; counts bounded by `limit`).

### Configuration (all via the secret store → injected as env at register time)

| Env var | Secret name (suggested) | Required | Effect |
|---|---|---|---|
| `NOTION_TOKEN` | `notion_token` | **yes** | Internal integration token |
| `NOTION_BUILDS_DB` | `notion_builds_db` | no | If set → `build_updates` queries this DB structurally; else search fallback |
| `NOTION_SENTIMENT_DB` | `notion_sentiment_db` | no | Same for `user_sentiment` |

DB ids are not secret, but the only injection path for a registered server is the
`env`→secret map, so they ride the secret store too (a generic KV). Absence is the
expected default (data shape is "mixed/unknown") → search fallback is the primary path.

## Data resolution (flexible, per Decision 2)

Each focused tool resolves its source at call time:

- **Structured path** — when the relevant `NOTION_*_DB` env is set: `POST
  /databases/{id}/query` with a date filter from `since`/`until`, sorted date-desc,
  page-size = `limit`. **Best-effort property mapping** (no hand-specified schema): pick
  the database's `title` property for `title`; the first `date`-typed property for
  `date`; the longest `rich_text` property for `summary`/`snippet`. A `version` field is
  populated only if a property named like `version`/`build` exists. Missing properties
  degrade to `null`, never error.
- **Search fallback** — when no DB is configured: `POST /search` with default keywords
  merged with the caller's `query` (`build_updates`: "release / patch / changelog /
  build"; `user_sentiment`: "feedback / sentiment / review"), filtered to pages, then
  fetch top hits to extract a date (page `created_time`/`last_edited_time` or a date
  property if present) and a snippet (first text blocks). `since`/`until` filter
  client-side on the resolved date.

`notion_search`/`notion_fetch` always hit `/search`, `/pages/{id}`,
`/blocks/{id}/children` directly. Id-or-URL is normalized (extract the 32-hex id from a
Notion URL; accept a bare id).

## Connect / data flow

```
# one-time connect (admin chat)
admin ──▶ secret_set notion_token <ntn_…>
admin ──▶ (optional) secret_set notion_builds_db <id> ; secret_set notion_sentiment_db <id>
admin ──▶ mcp_add name=notion command=python3 args=["-m","gaa.notion.server"]
              env={"NOTION_TOKEN":"notion_token",
                   "NOTION_BUILDS_DB":"notion_builds_db",
                   "NOTION_SENTIMENT_DB":"notion_sentiment_db"}
          └─▶ reload → render_config wires `notion` server, injects secrets,
              non-admin allow gains "notion__*"

# usage (enrich)
user ──▶ "why did D7 retention jump in May?"
agent ──▶ gaa__analyze(...)                      # what changed (quantitative)
agent ──▶ notion__build_updates(since,until)     # why  (qualitative)
agent ──▶ notion__user_sentiment(since,until)
agent ──▶ synthesized narrative

# usage (standalone Q&A)
user ──▶ "what shipped last week?"  ──▶ agent ──▶ notion__build_updates(...) ──▶ answer
```

To **disconnect/rotate**: `mcp_remove notion` / re-`secret_set notion_token …`. No
redeploy.

## Auth, errors, security

- **Auth:** `NOTION_TOKEN` from env (injected from the secret store). The Notion
  integration only sees pages/DBs explicitly shared with it — natural scoping; no extra
  ACLs in the agent.
- **Errors (never crash the stdio loop):** missing token →
  `{status:"error", error:"notion token not configured"}`; Notion 4xx/5xx →
  `{status:"error", error, http_status}`; `429` → surface `retry_after`; bad args →
  schema-validation message. All structured, mirroring `gaa.mcp.tools.run_tool`.
- **Security:** token never logged or echoed (consistent with the secret store's `0600`
  + names-only listing). All four tools **read-only** — no Notion writes — so no
  vStorage snapshot/mutation path is involved. Tool namespacing: `notion__*` (the `name`
  given to `mcp_add`).

## Testing

**Unit (TDD, matching repo discipline) — `tests/notion/`, Notion API fully mocked
(`httpx.MockTransport`); no live calls in CI:**
- `client.py` — request shaping (URL, headers incl. `Notion-Version`, bearer), each
  endpoint's response parsing, `429`/4xx/5xx surfacing, missing-token guard.
- `tools.py` — per tool: structured-DB path, search-fallback path, best-effort property
  detection (title/date/rich-text picks; missing props → null), date filtering, result
  truncation/caps, id-or-URL normalization, arg-schema validation, error shapes.
- `server.py` — `list_tools` returns the four specs; `call_tool` round-trips
  `run_tool` output as JSON `TextContent` (reuse the `_for_test_handles` style from
  `gaa/mcp/server.py`).

**Live spike (manual, gated; before trusting the mocks)** — one probe against a real
Notion test workspace + integration token: confirm `/search`, `/databases/{id}/query`,
`/pages/{id}`, `/blocks/{id}/children` response shapes match the parser. Documented under
`docs/spikes/`, not in CI.

## Deploy deltas

- **Code ships in the image** (the `gaa.notion` module) → a redeploy of
  `gaa-custom-agent` is required to make the module runnable; **connecting/activating** it
  afterward needs no redeploy (admin `secret_set` + `mcp_add`).
- No `render_config`, `pyproject`, or frontend change for the core server.
- Prereq for use: a Notion internal integration created in the target workspace, with the
  relevant pages/databases **shared to the integration**, and its token set via
  `secret_set`.

## Out of scope (follow-ups)

- **SOUL.md enrichment nudge** — persona guidance telling the agent to pull
  `build_updates`/`user_sentiment` for an analyze window. Optional and *separate*:
  ⚠️ per the deploy notes, persisted persona in vStorage overrides seed `SOUL.md` on
  boot, so on the already-deployed instance this needs an admin `self_edit`, not just a
  redeploy.
- **Write tools** (create/append page, comment) — read-only for now.
- **Sentiment scoring/aggregation** — return raw items; let the model summarize. A
  scored/aggregated tool can come later if the raw approach proves noisy.
- **Additional focused tools** (roadmap, incidents, KPIs-in-Notion — the "…" in the
  ask) — the generic `notion_search`/`notion_fetch` cover these today; promote to
  focused tools only if usage warrants.
- **Pipeline-level (code) enrichment** — backing a `gaa.core` stage with Notion context
  rather than agent orchestration.

---

## Live recon corrections (2026-06-16)

A live probe against the user's real workspace (integration **"01 [HGF] - Discord
Sentiments"**) — see `docs/spikes/notion-api-shapes.md` — corrected several assumptions.
**These override the body above.**

### 1. API model: data sources, version `2025-09-03`

The workspace uses Notion's **new data-source model**. The IDs the user provided are
**data-source IDs**, not classic database IDs:

- Schema: `GET /v1/data_sources/{id}` (returns `name` + `properties`).
- Rows: `POST /v1/data_sources/{id}/query` (same `sorts`/`filter`/`page_size` as the old
  database query).
- Search `filter.value` is `page` | **`data_source`** (the old `database` value is gone).
- `GET /v1/pages/{id}` and `GET /v1/blocks/{id}/children` are **unchanged**.
- The old `Notion-Version: 2022-06-28` + `POST /databases/{id}/query` returns **404** for
  these IDs. **Use `Notion-Version: 2025-09-03` throughout.**

Net effect on the design: `client.py` exposes `get_data_source` / `query_data_source`
(not `get_database` / `query_database`); env config is `NOTION_BUILDS_DS` /
`NOTION_SENTIMENT_DS`; `notion_fetch` falls back page → **data source**; `notion_search`
`type` enum is `["page", "data_source"]`.

### 2. The two accessible data sources (validated)

| Role | Data-source ID | Name | Detected title / date / text |
|---|---|---|---|
| Builds (best available) | `abee2267-021c-4a98-b91b-95d71e2a0cee` | **04_LiveOps Calendar Content** (45 rows) | `Event Name` / `Go-live Date` / `Brief` |
| Sentiment | `3590e4e2-3942-8032-8e8e-000bbb4da32a` | **10_Discord Sentiment** (5 rows) | `Report` / *(none → `created_time`)* / `note` |

The best-effort property detection (`_find_prop` for title/date, `_longest_rich_text` for
summary) maps **exactly** onto these schemas. Sentiment rows carry only a title + short
`note`; the substantive report text lives in the **page body**, reachable via
`notion_fetch` — documented for the agent, not auto-fetched per row (latency).

### 3. Builds ID discrepancy (action for the user)

The build-updates ID the user gave (`32b0e4e2-3942-80bf-8ea3-000b238300d1`) is **not
shared** with this integration (404 on every endpoint). The only build/release-shaped data
source the integration can see is **04_LiveOps Calendar Content** (`abee2267…`) — events
with go-live dates. The implementation wires that as the builds source for live
verification; the user can rebind to the intended database any time via
`secret_set notion_builds_ds <id>` once it is shared with the integration. This is config,
not code — no rebuild needed.

### 4. `_plain` property coverage

Real rows use `select`, `status`, `multi_select`, `created_time`, `unique_id`,
`checkbox`, `people`, `date`, `title`, `rich_text`. `_plain` is extended to cover these so
`notion_fetch` row summaries and date fallback are populated.
