# OpenClaw Chat Integration — Design

**Date:** 2026-06-12
**Status:** Approved (pending user review of this document)
**Depends on:** 2026-06-10-game-attribution-agent-design.md (the GAA runtime this integrates with)

## Summary

Put a platform-hosted OpenClaw instance between the existing React frontend (`gaa-test-frontend`) and the Game Attribution Agent (GAA) runtime, so that:

1. **End users chat with OpenClaw** from the existing React chat panel. OpenClaw answers small talk itself and answers analysis questions by calling the GAA runtime through a skill.
2. **An admin configures the system by chatting** — data sources, game profiles, and agent behavior. OpenClaw executes admin instructions by editing its own workspace files (`SOUL.md`, `AGENTS.md`, `skills/`, `memory/`) and by calling a new admin API on the GAA runtime.

Heavy/structured paths (CSV onboarding upload, report-pane dossier fetch) stay direct React → GAA as they are today.

## Spike results (verified 2026-06-12, all facts below tested live)

Instance: `gaa-chat` (`openclaw-04a7d7f2-2d99-4153-9e4e-00e38c9cc5b5`), template `2026.3.23-2`, flavor `runtime-s2-general-2x4`, MaaS-wired (Qwen3.5-27B default, Gemma 4 31B available). URL: `https://openclaw-111723-gaa-chat.agentbase-runtime.aiplatform.vngcloud.vn`.

| Fact | Verified how |
|---|---|
| Gateway WS accepts token auth with client id `openclaw-control-ui`, mode `webchat`, protocol 3, full operator scopes — **if** the `Origin` header matches the instance host. Template sets `dangerouslyDisableDeviceAuth: true`, so no device pairing is needed. | WS handshake + `config.get` returned the live `openclaw.json` |
| `config.set {raw, baseHash}` writes `openclaw.json`; server validates against schema and re-substitutes `__OPENCLAW_REDACTED__` secret placeholders. `gateway.http.endpoints.chatCompletions.enabled: true` hot-reloads — no restart. | Endpoint went 404 → 200 within seconds of the write |
| `POST /v1/chat/completions` (Bearer = gateway token) runs the full agent (tools included); `user` field scopes sessions; agents scope is `per-sender`. | PONG round-trip; exec test below ran through this endpoint |
| Config-by-chat works: agent appended an exact line to its own `SOUL.md` on request. | Read back via `agents.files.get` — line present, mtime updated |
| OpenClaw can call the GAA runtime: exec/curl to the GAA endpoint returned live `/health` JSON. | Chat round-trip |
| `openclaw.json` and workspace edits **persist across platform stop/start**. | Stop → start → re-verified endpoint (200) and `SOUL.md` line |
| Gateway WS methods available include `config.get/set`, `agents.files.list/get/set`, `skills.install`, `sessions.*`, `chat.send`. | `hello-ok` features list |

Constraint reminders: the gateway token is only returned at create time (ours is captured; it will live in `gaa-test-frontend/.env.local`, git-ignored, never committed); the token grants **full operator access**, so it must never reach the browser.

## Architecture

```
                    ┌────────────── React UI (gaa-test-frontend) ──────────────┐
                    │   Chat panel (user + admin)        Report pane           │
                    └──────┬───────────────────────────────────┬───────────────┘
                           │ /openclaw proxy (token injected   │ direct (unchanged)
                           │  server-side, SSE streaming)      │
                           ▼                                   ▼
              OpenClaw "gaa-chat"  ── GAA skill (curl) ──►  GAA runtime
              · /v1/chat/completions                        · /invocations (existing)
              · self-edits SOUL.md/AGENTS.md/skills/memory  · NEW admin actions
              · per-user sessions via `user` field          · NEW ConfigStore
```

Message routing inside OpenClaw is instruction-driven (its `AGENTS.md` + the GAA skill), not code:

- **Analysis question** ("why did revenue drop last week?") → call GAA `/invocations` with the message, get `job_id`, reply conversationally and embed the marker `[[gaa:job_id=<id>]]`. React strips the marker and polls GAA (`action=analyze_status`) for the dossier, rendering the report pane exactly as today.
- **Admin instruction** ("switch benchmarks to live crawl", "answer in Vietnamese from now on") → either call a GAA admin action or edit its own workspace files, then confirm in chat what changed.
- **Anything else** → answer directly from its own LLM/memory.

## Components

### 1. OpenClaw bootstrap — `scripts/openclaw_bootstrap.py` (GAA repo)

A repeatable, idempotent script (promoted from the spike code) that connects to the gateway WS (control-ui client identity + `Origin` header + token) and:

1. Enables `gateway.http.endpoints.chatCompletions` via `config.get` → splice → `config.set` (no-op if already enabled).
2. Writes the **GAA skill** into the workspace via `agents.files.set`:
   - `skills/gaa/SKILL.md` — what the GAA is, the `/invocations` action catalog (analyze, analyze_status, profile ops, admin actions), curl recipes, the `[[gaa:job_id=...]]` reply convention, and when to use which action.
   - The GAA endpoint URL and `GAA_ADMIN_KEY` go into the workspace `.env` (referenced from the skill, never inlined in SKILL.md).
3. Seeds `AGENTS.md` additions: role red-lines (admin actions only for sessions whose user id starts with `admin:`), reply-marker convention, default language policy.

Inputs via env/args: OpenClaw URL, gateway token, GAA endpoint, GAA admin key. Output: a printed checklist of what it changed/verified. The script doubles as the integration smoke test (probe endpoint, list workspace files).

Day-to-day refinement after bootstrap is **config-by-chat** — the admin instructs the agent in plain language and it updates its own files (verified to persist).

### 2. GAA runtime — runtime-changeable config + admin API

**`ConfigStore`** (`src/gaa/store/config_store.py`, SQLite alongside ProfileStore):

- Keys (initial set): `benchmark_mode` (`snapshot`|`crawl`), `roblox_discover_url_tmpl`, `roblox_series_url_tmpl`, `steam_series_url_tmpl`, `perplexity_api_key`, `signals_url_tmpl`, `behavior_instructions` (free text).
- Resolution order: ConfigStore value → env var → built-in default. Settings are read **per job/request** (providers and signal sources are constructed from current config when a job starts, not frozen at process startup — a focused refactor of the wiring in `main.py`).

**Admin actions** on the existing `/invocations` entrypoint, guarded by a payload field `admin_key` == env `GAA_ADMIN_KEY` (payload-based rather than header-based because the AgentBase SDK does not guarantee arbitrary header passthrough to the handler; constant-time compare; structured 403-style JSON error on mismatch; admin actions disabled entirely if `GAA_ADMIN_KEY` unset):

| Action | Effect |
|---|---|
| `admin_get_config` | Returns all config keys with their resolved values and origin (store/env/default); secrets masked to last 4 chars |
| `admin_set_config` | Sets/clears one or more keys; validates `benchmark_mode` enum and URL-template shape; returns the new resolved config |
| `admin_set_behavior` | Sets `behavior_instructions` (size-capped, e.g. 2 000 chars) |
| `list_profiles` | Names + active flag (wraps existing ProfileStore) |
| `set_active_profile` | Switches the active game profile |

**Behavior injection:** `behavior_instructions` is appended to the synthesizer and markdown/report prompt context (clearly delimited as operator preferences, e.g. output language, focus metrics). It must never override the evidence-citation rules — the validator still enforces ledger citations.

### 3. Frontend — `gaa-test-frontend`

- **Proxy route** `/openclaw/*` in `vite.config.ts` → OpenClaw URL, injecting `Authorization: Bearer <token>` server-side from `.env.local` (`OPENCLAW_URL`, `OPENCLAW_TOKEN`). The token never ships to the browser.
- **ChatPanel**: free-text path switches to `POST /openclaw/v1/chat/completions` with `stream: true` (SSE) and `user` = existing userId (admin sessions: `admin:<userId>`). On reply, strip `[[gaa:job_id=...]]` markers; when present, start the existing GAA polling flow (`useAnalyzePoller`) so the report pane renders unchanged. Conversation history is OpenClaw's job (persistent sessions per `user`); the React side keeps sending only the new message.
- **Admin toggle** in the connection panel: switches the session to the `admin:` prefix and reveals admin quick-chips ("show current config", "switch to live crawl", "set report language to Vietnamese").
- CSV onboarding (propose/confirm) and the Console tab remain direct React → GAA, unchanged.

## Error handling

- **OpenClaw unreachable / 5xx / timeout** → ChatPanel shows a retryable error bubble and offers "send directly to GAA" (the legacy path stays available behind the existing api.ts functions).
- **Marker present but GAA poll fails** → report pane shows the existing polling error state; the chat reply still stands on its own.
- **Admin action with wrong/missing key** → GAA returns a structured 403 payload; the skill instructs OpenClaw to report "not authorized" rather than retrying.
- **OpenClaw long tool-runs** (it curls GAA, which can take seconds) → frontend SSE timeout set generously (≥120 s) with streaming keep-alive; quick-chips warn the user that analysis kicks off a job.
- **Bootstrap drift** (e.g. platform version switch resets workspace) → re-running `openclaw_bootstrap.py` restores endpoint + skill; the script is the source of truth for the baseline workspace.

## Security posture (accepted trade-offs)

- Single OpenClaw instance, **soft role separation**: `AGENTS.md` tells the agent to refuse admin actions for non-`admin:` sessions, and the GAA admin key is enforced server-side at GAA. Because OpenClaw is one trust boundary, a determined user could prompt-inject it into using the admin key. Accepted for the demo; documented. Hardening path (no design change elsewhere): a second, admin-only OpenClaw holds the key and the user-facing instance gets a skill without admin actions.
- Gateway token handling: server-side proxy only; `.env.local` git-ignored; token rotation = recreate instance (platform limitation) and re-run bootstrap.
- `GAA_ADMIN_KEY` is a new secret set on the GAA runtime env and in the OpenClaw workspace `.env` by the bootstrap script.

## Testing

- **GAA (pytest, extends existing suite):** ConfigStore CRUD + resolution order; admin-key auth (allow/deny/unset); `admin_set_config` validation; behavior-instruction injection into synth prompt (and that citation validation still applies); per-job provider construction honors config changes without restart.
- **Bootstrap/integration (script):** endpoint probe (200), workspace file presence, skill content hash; runnable any time as a smoke test.
- **End-to-end (manual demo script):** user asks "why did revenue drop?" → chat reply + report renders; admin toggles on, says "switch benchmarks to live crawl and answer in Vietnamese" → `admin_get_config` reflects it and the next analysis answer is in Vietnamese with crawl-tier evidence.

## Out of scope

- Telegram/Zalo channels (can be added only at instance create; not needed for this topology).
- Hard multi-tenant isolation between end users (OpenClaw single-trust-boundary; per-`user` session isolation is sufficient for the demo).
- Production proxy server (Vite dev proxy is the demo deployment; a thin Node/edge proxy is the production equivalent, same contract).
- Streaming GAA job progress through OpenClaw (React polls GAA directly, as today).
