# App Store Discovery (name/genre → app_id) — Design

**Date:** 2026-06-17
**Status:** Design (approved in brainstorming; pending spec review → plan)
**Branch:** `feat/gaa-on-openclaw`
**Builds on:** the Sensor Tower browser-proxy (`2026-06-16-sensor-tower-browser-proxy-design.md`).

## Goal

Let the agent **find Sensor Tower app ids from a game name or genre** itself, instead of asking
the user to paste an id. This removes the `need_app_id` friction that surfaced in the live smoke
(the agent offered "give me a genre, I'll search" but the ST connector has no discovery — every ST
tool is id-based).

## Context / why

The Sensor Tower connector exposes 6 read-only, **id-based** tools and **no app discovery**
(no search-by-name, no search-by-genre; `search_optimization` is keyword-ranking for a *known*
app, not app search). Live smoke confirmed the data path works end-to-end, but the agent can't
turn "Mobile Legends" / "MOBA" into an `app_id`.

**Key finding (verified 2026-06-16):** the **public iTunes Search API** is free, no-auth, fast
(~0.5s), structured, and the runtime can call it directly (it's a public Apple endpoint with no
origin allowlist — unlike ST, no 403). A probe of `term=MOBA&entity=software` returned real MOBA
games with their App Store `trackId`s (LoL: Wild Rift `1480616990`, Honor of Kings `1619254071`,
Mobile Legends, Arena of Valor, Pokémon UNITE) plus name/publisher/genre. **For iOS apps the App
Store `trackId` is the Sensor Tower iOS `app_id`**, so discovered ids feed straight into the
existing `st_*` tools.

## Decisions (from brainstorming)

1. **Approach: public App Store (iTunes Search) — server-side.** Rejected: asking the
   aawp-connector team to expose ST's search endpoints (out of our control, slow, still
   browser-proxied/403); web search via Perplexity (unstructured, imprecise for ids).
2. **Scope: name resolution first, genre second** — and the iTunes Search API handles *both*
   (names and genre-ish terms) in one tool, so v1 ships one tool; true ranked top-charts (RSS)
   is a deferred phase-2 nicety.
3. **iOS-first** — discovered `trackId` = ST iOS `app_id`; Android (package-name id, no official
   search API) and unified/cross-platform discovery are deferred.

## Architecture

Server-side only — no browser, no OAuth, no relay. A plain httpx call inside the gaa MCP server,
like the existing analysis tools.

### New module: `gaa/appstore/search.py`

| Unit | Responsibility | Depends on |
|---|---|---|
| `search_apps(query, *, country="US", limit=8) -> list[dict]` | GET `https://itunes.apple.com/search?term=<query>&entity=software&country=<c>&limit=<n>`; map each result → `{"app_id": trackId, "name": trackName, "publisher": sellerName, "genre": primaryGenreName, "platform": "ios", "url": trackViewUrl}`. Raise on network/non-200 (caller maps to a structured error). | `httpx` |

### Changed: `gaa/mcp/tools.py`

One new tool, routed **server-side** (like the analysis tools — NOT through the `st_*`
guard/cache/relay path):

- `appstore_search(query, country?, limit?)` → `{"apps": [ {app_id, name, publisher, genre, platform}, ... ]}`
  on success; `{"apps": []}` when no matches; `{"status": "error", "error": "appstore_unavailable",
  "detail": ...}` on iTunes failure.
- Schema: `query` (string, required); `country` (string, optional, default "US"); `limit`
  (integer, optional, default 8).

### Data flow

```
LLM: appstore_search("Honor of Kings")
  gaa server: httpx GET iTunes Search → map results
  → {"apps": [{"app_id": 1619254071, "name": "Honor of Kings", "publisher": "...", "genre": "Games", "platform": "ios"}]}
LLM: picks the right app; optionally st_set_app_id("competitor:hok", 1619254071) to persist it
LLM: st_app_performance(app_ids=[1619254071])  → existing browser-proxy → real ST downloads/revenue
```

This kills the `need_app_id` friction: the agent resolves names/genres → ids itself, then pulls ST data.

## ID mapping + the Phase-0 verify

`trackId` (iOS App Store id) **is** the Sensor Tower iOS `app_id` (ST uses App Store IDs for iOS).
High confidence, but verified cheaply once live: take a discovered id (e.g. `1480616990`) →
`st_app_performance(app_ids=[1480616990])` while connected → expect real data, not "Failed to find
any apps." That is the acceptance check for the bridge.

## Scope (iOS-first) — explicit

- Discovered ids are iOS App Store ids → use with the **app_id-based** ST tools
  (`st_app_performance`, `st_download_channel`, `st_app_store`, `st_search_optimization`) for **iOS**
  data.
- `st_unified_app_performance` needs a *unified_app_id* (a different ST id iTunes doesn't provide),
  so discovered ids route to the **non-unified** tools. The playbook says so.
- **Out of scope (deferred):** Android discovery (ST id = Google Play package name; no official
  Google search API), unified/cross-platform discovery, and ranked top-charts via iTunes RSS feeds.

## Error handling (all structured, non-fatal — discovery is enrichment)

- iTunes timeout / non-200 / network error → `{"status": "error", "error": "appstore_unavailable",
  "detail": ...}` → the agent falls back to asking the user for an id.
- No matches → `{"apps": []}` → the agent suggests a different name/spelling.
- No caching in v1 (iTunes is free and ~0.5s; YAGNI).

## Testing

- `search.py` — mock `httpx` with a captured iTunes payload: assert the field mapping
  (`trackId`→`app_id`, name/publisher/genre/url/platform), the `limit`/`country` query params, the
  empty-results case, and the error path (non-200 / timeout raises).
- `tools.py` — `appstore_search` routing, the success/empty/`appstore_unavailable` result shapes.
- All server-side (no browser/relay mocking).
- **Phase-0 live verify:** a real iTunes call returns mapped candidates, AND a discovered `trackId`
  → `st_app_performance` returns real ST data (the bridge holds).

## Playbook + deploy

- Update `openclaw/AGENTS.md`: to get an app id, the agent calls `appstore_search(name or genre)`,
  picks the right app, and uses its `app_id` with the `st_*` tools (and `st_set_app_id` to remember
  it) — instead of asking the user. Discovered ids are iOS App Store ids → use the non-unified ST tools.
- **Server-side-only change** (no frontend/env changes) → a single agent rebuild + redeploy, plus
  applying the playbook to the live instance (admin `self_edit`, per the persisted-workspace gotcha).

## Out of scope (Phase 2+)

- Ranked top-charts (iTunes RSS top-grossing/top-free by genre).
- Android + unified/cross-platform discovery.
- Caching discovery results.
- Asking the aawp-connector team to expose ST-native search/top-charts (the long-term ideal; a
  request to that team, not buildable here).
