# GAA as One Custom Agent — Design (supersedes the OpenClaw-hosting combine)

**Status:** Approved design (pre-implementation)
**Date:** 2026-06-13
**Supersedes:** the OpenClaw-hosting combine (spec `2026-06-13-single-agent-combine-design.md` §10–11 + Plan 3). The `gaa` core/CLI/run-dirs/lab/tools (Plans 1–2c) are **reused unchanged**; only the *host* changes.
**Scope:** the **backend** (the Custom Agent). The frontend (ai-chatbot clone) is a separate spec, designed after this one is approved.

---

## 1. Why this exists (the pivot)

The single-agent combine hosted analysis *inside* an OpenClaw instance. Plan-4 spikes proved OpenClaw **cannot deliver an interactive HTML dossier to a browser** — there is no byte-exact container→browser channel:

| Channel (OpenClaw) | Result |
|---|---|
| `agents.files.get` | filename-whitelist; rejects arbitrary/nested files (incl. the 4.58 MB `report.html`) |
| chat-exec + base64 | garbles content (~1-char flips) |
| `/v1/chat/completions` response | final Qwen prose only — no tool/exec output (verified non-streaming + SSE) |
| custom HTTP endpoint | unsupported; config exposes only `chatCompletions` |
| modify the template image | impossible — create API takes only version/flavor/env/channels; runtime patching is unsupported/reset-prone |

**Root cause:** OpenClaw is a *locked template* — chat in, prose out. A **Custom Agent runtime is your own image**: per the platform contract it must only "listen on :8080 + `GET /health`; how it serves requests is entirely up to the user." So a Custom Agent can serve the dossier (and anything else) over HTTP — which is exactly what an interactive frontend needs.

**Decision:** rebuild GAA as **one Custom Agent** — a single image we control that does chat **and** analysis **and** serves the dossier. This is the combine "done right," on a host that can actually serve artifacts.

## 2. Goals / non-goals

**Goals**
- A single Custom Agent serves: conversational chat, structured analysis, and byte-exact dossier/artifact delivery to a browser.
- Interactive dossier in the browser (Claude-artifact style: served HTML rendered in a sandboxed iframe).
- A persistent, growable toolbox: `gaa.lab` (Tier 3) + tool promotion (Tier 2.5) + runtime config work in-process, and durable state survives redeploys.
- Reuse the entire `gaa` analysis core/CLI/run-dirs/lab/tools (Plans 1–2c).
- **Faithfully clone the OpenClaw agent's general behaviors** (audited from the live instance), on a host we control: its **persona** (`SOUL.md`), **self-memory/continuity** (`MEMORY.md` it reads + updates), **general capabilities** (arbitrary exec + headless browsing), and its **models** (Gemma 4 31B for reasoning). The Custom Agent is a *superset*: OpenClaw's general agent + the GAA specialization + HTTP dossier serving (which OpenClaw couldn't do).

**Non-goals**
- OpenClaw (retired from the architecture).
- Hard multi-tenant isolation (one deployment; sessions scope conversations, not data — unchanged).
- Real-time/streaming data ingestion (batch, unchanged).
- A *public* general agent: because it has arbitrary exec/browse, `/chat` is **token-gated** (not open) — see §7.

## 3. Architecture

A single Docker image (Custom Agent runtime), a **FastAPI app on port 8080**. We use FastAPI (not the `greennode-agentbase` SDK's `/invocations`-only entrypoint) because we need custom routes — notably the dossier GET route. Routes:

| Route | Purpose | Auth (§7) |
|---|---|---|
| `POST /chat` | The conversational agent loop. SSE streaming. Stateless (client sends `messages[]`). | Bearer `GAA_AGENT_TOKEN` |
| `POST /invocations` | Structured analysis API (programmatic + the frontend's non-chat paths, e.g. CSV onboarding). | Bearer `GAA_AGENT_TOKEN` |
| `GET /runs/<run_id>/<artifact>` | Serves a run's `report.html` / `summary.md` / `activity.log` / `ledger.jsonl` **byte-exact over HTTP**. | open (read-only) |
| `GET /health` | 200 when ready (platform marks runtime ACTIVE). | open |

All requests resolve the shared `GaaContext` (the Plan-1 `build_context` composition root) once at startup; handlers run the `gaa` pipeline/stores/registry **in-process**.

## 4. The chat agent loop (`/chat`) — a full clone of the OpenClaw agent

A **full agent loop run in our code** — replicating OpenClaw's agent (audited live), but in-process so tool results are byte-exact (no garbling). **Stateless:** the frontend sends the full `messages[]` (OpenAI style); the loop runs over that history each request.

**System prompt = persona + memory + instructions + tool guide**, assembled per request from:
- **`SOUL.md`** — the agent **persona** (cloned from OpenClaw's: genuinely-helpful-not-performative, has opinions, resourceful-before-asking, respects privacy, concise/thorough, "your files are your memory — evolve them"). Editable at runtime (self-editing) and persisted (§6).
- **`MEMORY.md`** — cross-session **self-memory/continuity** (notes the agent reads + updates). Editable, persisted.
- **`AGENTS.md`** red-lines (admin gating, secrets, run-id discipline, tier-3 read-only). *The OpenClaw "budgets" rule is dropped — analysis runs in-process, no backgrounding.*
- The **gaa skill decision-guide** (when to use which gaa action).

**Manual JSON tool-loop** (not native function-calling — MaaS tool support is unverified/quirky):
1. The model replies with **either** `{"action": "<name>", "args": {…}}` **or** `{"final": "<narrative>"}` (tolerant `_extract_json`).
2. If an action: **dispatch in-process** against `GaaContext`, append the result, loop (bounded iteration cap to prevent runaway).
3. If `final`: that narrative is the assistant reply.

**Tool set (cloned superset — all in-process):**
- **GAA actions:** `analyze`, `segments`, `detect`, `market`, `signals`, `synth`, `report`, `status`, `jobs`, `onboard_propose`, `onboard_confirm`, `profile_list`, `profile_use`, `config_get`, `config_set`, `doctor`, `tools_list`, `tools_promote`, `tools_run`.
- **General agent capabilities (cloned from OpenClaw):** `exec` (arbitrary shell), `browse` (headless browser fetch/interact), and `self_edit` (update `SOUL.md`/`MEMORY.md`). These make it a general agent, not just an analyst — and are the reason `/chat` is **token-gated** (§7). `exec`/`browse`/`self_edit`/admin-class actions require the admin context; analysis actions are open within an authenticated session.

**Models (cloned from OpenClaw):** orchestration **and** synthesis use **Gemma 4 31B** (`google/gemma-4-31b-it`, reasoning, 200K ctx — OpenClaw's default), via MaaS. (Qwen 3.5 27B remains available/configurable as a fallback; switching synthesis to Gemma 4 requires re-verifying the `AttributionHypothesis` JSON output — see §10/§13.)

**Analysis runs to completion in-process.** `analyze` advances the run through all stages synchronously (`pipeline.advance(run, deadline=None)` — the budget/step machinery existed only for OpenClaw's exec timeout). The loop ends its reply with the marker:

```
[[gaa:run_id=<run_id>]]
```

**Active run for follow-ups:** stateless — the run_id is in the conversation history; the system prompt instructs reuse for drilldowns. No server-side session store (the *persona/memory* persist via §6, but per-conversation history is client-held).

**Streaming (SSE):** final narration streams token-by-token; activity events ("running segment analysis…") stream as actions dispatch. (Internal tool-decision calls aren't streamed.)

## 5. Dossier delivery (the whole point)

The frontend detects the `[[gaa:run_id=…]]` marker, strips it from the visible text, and fetches `GET /runs/<id>/report.html` from the **same Custom Agent endpoint** → renders it in a **sandboxed iframe** (`sandbox="allow-scripts"`, `srcdoc`/blob) — Claude's exact artifact mechanism. Byte-exact HTTP handles the 4.58 MB self-contained Plotly dossier directly. The analysis pane may also fetch `summary.md` / `activity.log` / `ledger.jsonl` for a live trace. The route reads from the run store (`RunStore.path_for`), restricted to files under `data/.../runs/<id>/` (no path traversal).

## 6. Persistence — vStorage S3 (real durability)

The Custom Agent filesystem is ephemeral and the runtime can't mount a volume, so durable state is persisted to **VNG vStorage** (S3-compatible object storage; endpoint e.g. `https://hcm04.vstorage.vngcloud.vn`, HTTPS, boto3).

- **`src/gaa/persist.py`** — a small layer with `restore()` and `snapshot()`:
  - **`restore()`** (called at server startup): pulls the latest state tarball from the bucket and extracts it into the workspace.
  - **`snapshot()`** (called after each durable mutation — `onboard_confirm`, `tools_promote`, `config_set`, **`self_edit`** of SOUL.md/MEMORY.md): tars the **durable subset** and puts it to the bucket.
- **Durable subset:** `SOUL.md` + `MEMORY.md` (the agent's persona + self-memory — the OpenClaw-continuity files, editable at runtime), `data/tools/` (promoted-tool registry), `gaa-config.toml`, `gaa.sqlite` (profiles), and the metrics Parquet dir. **Runs are NOT persisted** (regenerable; a redeploy loses old run dossiers, which a re-ask reproduces — keeps the snapshot small).
  - SOUL.md/MEMORY.md ship as seed files in the image (the cloned OpenClaw persona + an empty memory); on first `restore()` from an empty bucket they seed the snapshot, after which the persisted copies (which the agent has evolved) win. This is exactly how OpenClaw makes its "your files are your memory" persona survive — here backed by S3 instead of a mounted workspace.
- **Implementation:** boto3 S3 client against the vStorage endpoint; generalizes the Plan-2c `tools_registry.export/import` tarball pattern to whole-durable-state. New dependency: `boto3`.
- **Config (env):** `VSTORAGE_ENDPOINT`, `VSTORAGE_BUCKET`, `VSTORAGE_ACCESS_KEY`, `VSTORAGE_SECRET_KEY`. If unset, persistence is a no-op (local-only) — so tests + local dev need no S3.
- **Net:** runtime-grown toolbox + config + onboarded games survive redeploys/restarts — OpenClaw-parity durability, without a volume.

**Prerequisite (one-time, human):** create a vStorage bucket + an S3 access/secret key pair in the VNG Cloud console; put them in the runtime's env.

## 7. Security posture

Cloning OpenClaw's **general capabilities** (arbitrary `exec` + headless `browse`) means `/chat` can run any code on the container — that is *remote code execution by design*, the same as OpenClaw. OpenClaw made this safe by putting the whole agent **behind its gateway token**; we do the same. So, unlike the pre-teardown design, **`/chat` is NOT open** — it is token-gated, and the open surface is only the read-only artifact routes.

- **`/chat` and `/invocations` require a bearer token** — `Authorization: Bearer $GAA_AGENT_TOKEN` (constant-time compare against runtime env `GAA_AGENT_TOKEN`). The token is held **server-side by the frontend proxy** (a Next.js route handler), never shipped to the browser. No token / wrong token → 401. This is the OpenClaw-gateway-token model: the agent is powerful, so reaching it is gated. **If this token leaks, it is full RCE on the container** — treat it like the OpenClaw gateway token (rotate via redeploy; never commit; `.dockerignore` excludes it).
- **Artifact routes are open** (`GET /runs/<id>/report.html` + sibling artifacts, `GET /health`) — read-only, path-traversal-restricted to a run dir, no secrets. This lets the iframe load the dossier without threading the agent token into the browser. (Run ids are unguessable slugs; acceptable for a demo. Hardening path: signed URLs.)
- **Within an authenticated `/chat` session, capabilities are tiered:**
  - *Analysis actions* (analyze, segments, …, dossier) — allowed.
  - *Powerful/admin actions* (`exec`, `browse`, `self_edit`, `config_set`, `onboard_confirm`, `profile_use`, `tools_promote`, `tools_run`) — require an **admin context**, signalled by a separate `admin_key` (env `GAA_ADMIN_KEY`, constant-time) that the proxy sets for admin users. So a non-admin authenticated user can analyze + read, but only an admin can run shell/browse/self-edit/mutate. With `GAA_ADMIN_KEY` unset, these are refused. (Two-level: the agent token gates *reaching* the agent; the admin key gates the *dangerous tools within it* — defence in depth for the cloned RCE surface.)
- vStorage keys + LLM keys + both gate tokens live only in the runtime env (never in the image; `.dockerignore` excludes `.env`/secrets).

## 8. Reuse vs. new code

**Reused unchanged** (Plans 1–2c): `gaa.core` (analytics/modules/synth/render/schema/adapters/crawl/sources/store/onboarding/llm), `gaa.runs` (Run/RunStore/pipeline), `gaa.config`, `gaa.lab`, `gaa.tools_registry`, `gaa.cli` (the CLI stays — standalone use + a shared action layer).

**New:**
```
src/gaa/
├── server/
│   ├── __init__.py
│   ├── app.py        # FastAPI app + routes (/chat, /invocations, /runs/<id>/<artifact>, /health) + token/admin gating
│   ├── agent.py      # the manual JSON tool-loop + SSE; assembles the SOUL.md+MEMORY.md+AGENTS.md system prompt
│   ├── actions.py    # action-name → in-process handler map (shared with the CLI command fns)
│   ├── capabilities.py  # general agent tools cloned from OpenClaw: exec (subprocess), browse (headless), self_edit (SOUL/MEMORY)
│   └── persona.py    # load/inject SOUL.md + MEMORY.md; self_edit writes them back + triggers persist.snapshot()
├── persist.py        # vStorage S3 snapshot/restore
SOUL.md               # seed persona (cloned from the audited OpenClaw SOUL.md)
MEMORY.md             # seed self-memory (starts ~empty; the agent appends to it)
Dockerfile            # python:3.11-slim + gaa + fastapi/uvicorn/boto3 + headless browser; serves :8080
```
To avoid duplicating logic, the analysis/onboarding/admin actions are factored into `gaa/server/actions.py` (or a shared `gaa.actions`) that **both** the CLI commands and the chat loop call — one source of truth per action. The general capabilities (`exec`/`browse`/`self_edit`) are chat-loop-only (not CLI commands) and live in `capabilities.py`, dispatched by the same action map but admin-gated (§7).

**New deps:** `fastapi`, `uvicorn`, `boto3`, and a headless-browser stack for `browse` (Playwright + chromium, or a lighter `requests`+readability fetch if full browser automation proves too heavy for the image — decided in planning; see §13).

## 9. Deployment

- **Dockerfile**: `python:3.11-slim`, `pip install -e .` (+ fastapi/uvicorn/boto3 + the headless-browser stack for `browse`), `CMD` runs uvicorn serving `gaa.server.app:app` on `:8080`. The browser stack (chromium + Playwright, if chosen) adds weight (~several hundred MB) and a `playwright install chromium` build step — the reason §13 keeps a lighter fetch-only fallback open.
- Build `linux/amd64`, push to the managed Container Registry (`vcr.vngcloud.vn/111480-abp111723/gaa`), deploy as a **Custom Agent runtime** (`/agent-runtimes`, PUBLIC, 1 replica, flavor ~`runtime-s2-general-2x4` — sized up if the browser stack needs more memory).
- Runtime env: `LLM_*` (pointed at MaaS **`google/gemma-4-31b-it`** as the primary model — OpenClaw's default — for both orchestration and synthesis; Qwen as a configurable fallback), `PERPLEXITY_API_KEY`, `GAA_BENCHMARK_MODE`, `GAA_AGENT_TOKEN` (gates `/chat`+`/invocations`), `GAA_ADMIN_KEY` (gates dangerous tools), `VSTORAGE_*`.
- `GET /health` → ACTIVE. Endpoint URL is public.
- **OpenClaw `gaa` instance — kept temporarily, torn down later.** It is no longer part of the target architecture, but is kept ACTIVE for now as a live reference to learn from its agent design/behaviors while building the Custom Agent. It is **still billed** — delete it via `/agentbase-teardown` once the Custom Agent is built + verified (don't delete proactively). Plan 3's `openclaw_install.py` + `workspace/` skill files are retired (kept on history; the gaa skill content informs the chat loop's system prompt).

## 10. Testing

- **Offline (pytest):** the agent loop tested with `FakeLLM` scripted to emit specific tool-decisions then a final (deterministic, no network); the action dispatch tested against fixture runs; dossier routes tested via FastAPI TestClient against a fixture run dir; **auth tested** (no/bad agent token → 401 on `/chat`+`/invocations`; non-admin context → `exec`/`browse`/`self_edit`/mutating actions refused; admin key → allowed; artifact routes open); **`self_edit`** tested for SOUL.md/MEMORY.md write-back + that it triggers `persist.snapshot()`; **`exec`** tested against a sandboxed temp command; **persona assembly** tested (system prompt contains SOUL.md + MEMORY.md content); `persist.py` tested against a stubbed/in-memory S3 (moto or a fake client) for snapshot/restore round-trip incl. the SOUL/MEMORY seed-vs-persisted precedence; the Plans 1–2c suite (248) stands.
- **Gemma-4 synthesis re-verification (gating):** switching synthesis from Qwen 3.5 27B to Gemma 4 31B changes the model that emits the `AttributionHypothesis` JSON. Add a check (live or recorded-fixture) that Gemma reliably produces schema-valid synthesis output before relying on it as the default; if it regresses, keep Qwen as the synthesis model via config while still using Gemma for orchestration.
- **Live:** deploy the Custom Agent; verify `/health`, `/chat` (with agent token) → analysis → marker, `GET /runs/<id>/report.html` returns the dossier, a follow-up drilldown, an admin-gated action with/without the admin key, an `exec`/`browse` round-trip, a `self_edit` that survives a redeploy (MEMORY.md persisted via vStorage), and a vStorage snapshot/restore across a redeploy.

## 11. The frontend (separate spec, next)

Clone `vercel/ai-chatbot`, gut NextAuth/Postgres to single-user, point chat at `POST /chat` (the Custom Agent) via a **Next.js server route that injects `Authorization: Bearer $GAA_AGENT_TOKEN`** (and the admin key for admin users) server-side — the browser never sees either token (this is what makes the cloned RCE surface safe, §7). Detect the `[[gaa:run_id=…]]` marker → fetch `GET /runs/<id>/report.html` (open route) → sandboxed iframe (the artifacts pane), with a live trace from the other run artifacts. CSV onboarding uploads via `POST /invocations` (proxied with the token). Designed in its own brainstorming cycle after this backend spec is approved.

## 12. Key decisions

| Decision | Alternative | Why |
|---|---|---|
| Custom Agent host | OpenClaw template | only a Custom Agent can serve the interactive dossier (spikes proved OpenClaw can't) |
| FastAPI app | restore the SDK `/invocations` shell | need custom GET routes (dossier); contract only requires :8080 + /health |
| Full in-process agent loop | deterministic router | in-process tool results are byte-exact; replicates OpenClaw's UX without its fragility (user choice) |
| Manual JSON tool-loop | native function-calling | MaaS tool support unverified + quirky (Qwen and Gemma alike); manual loop is robust + matches existing `_extract_json` |
| Stateless (client history) | server session store | matches the frontend + OpenAI style; conversation is the single source of truth; no state to wipe |
| vStorage S3 persistence | AgentBase Memory; volume; ephemeral | Memory is conversational (not files); no volume mount on Custom Agents; S3 cost is negligible and gives real durability (user choice) |
| Persist setup-state only (not runs) | persist everything | keeps snapshots small; runs are regenerable |
| Clone OpenClaw's full agent (persona/memory/exec/browse) | analyst-only chat agent | user choice: faithfully reproduce the OpenClaw agent on a host we control — a superset, not a downgrade |
| Self-evolving SOUL.md + MEMORY.md (persisted to S3) | static system prompt | clones OpenClaw's "your files are your memory" continuity; survives redeploys via vStorage |
| Gemma 4 31B for chat **and** synthesis | keep Qwen for synthesis | clones OpenClaw's default model; Qwen kept as configurable fallback pending re-verification (§10) |
| `/chat` token-gated (`GAA_AGENT_TOKEN`) + admin key for dangerous tools | open `/chat` | cloned exec/browse = RCE; OpenClaw gated it behind the gateway token, so we gate too (two-level, §7) |
| Re-introduce `admin_key` | open admin | the endpoint is reachable; gate state-changing + dangerous (exec/browse/self_edit) actions |

## 13. Risks / open items

1. **MaaS function-calling / JSON reliability** — mitigated by the manual JSON loop + tolerant parsing + bounded iterations; verify live that the orchestration model (Gemma 4 31B) reliably emits the action JSON.
2. **In-process analysis latency** — a full analyze (crawl + N synth samples + render) in one request is ~10–30 s; SSE streams progress so the UX isn't a blank wait. If too slow, revisit async.
3. **vStorage snapshot granularity** — whole-durable-state tarball after each mutation is coarse; fine at low write frequency; per-file sync is a later optimization.
4. **Dossier size** — 4.58 MB inline Plotly loads fine over HTTP; if it grows, switch `report.html` to CDN-Plotly (smaller) — a `render` change, not an architecture change.
5. **`show_thinking`** (deferred from the combine) — now trivially feasible (the server can stream synthesis reasoning); revisit in implementation.
6. **Cloned RCE surface** — `exec`/`browse` make `/chat` capable of arbitrary code execution by design (OpenClaw parity). Mitigated by the agent-token gate (only the proxy can reach `/chat`) + admin-key gate on the dangerous tools (§7), but the residual risk is real: an agent-token leak = full RCE. Accept for the demo; the hardening path is real per-user auth + dropping `exec` to an allow-list. Document the token as high-sensitivity.
7. **Image weight from the browser stack** — Playwright+chromium adds hundreds of MB + a build step + more runtime memory. If it bloats the image or the build, fall back to a lightweight `requests`+readability fetch for `browse` (covers most "look something up" cases; loses JS-rendered pages). Decide in planning by measuring the image.
8. **Gemma-4 synthesis regression** — switching synthesis off the verified Qwen path risks schema-invalid `AttributionHypothesis` output; gated by the §10 re-verification, with Qwen as a config fallback. Don't make Gemma the synthesis default until verified.
9. **Self-editing memory drift** — a self-evolving MEMORY.md/SOUL.md could accumulate noise or be poisoned via a crafted conversation (it's writable by the agent on admin turns). Low stakes for a single-user demo; keep snapshots so a bad edit is recoverable by restoring a prior snapshot, and consider a size cap / human-review of MEMORY.md.

---

## 14. As-built notes & deploy runbook (backend implemented 2026-06-13)

The backend was implemented on branch `feat/gaa-custom-agent-backend` via 9 TDD tasks (plan: `docs/superpowers/plans/2026-06-13-gaa-custom-agent-backend.md`). **294 tests pass.** New code: `src/gaa/server/{__init__,app,agent,actions,capabilities,persona}.py`, `src/gaa/persist.py`, `src/gaa/data/seed/{SOUL.md,MEMORY.md}`, `Dockerfile`, `.dockerignore`.

### Implementation refinements (deltas from the spec, discovered during build/review)
- **Dev env:** the repo uses `uv` + a `.venv` (run tests `.venv/bin/python -m pytest`). The Docker image installs via `pip` inside `python:3.11-slim`.
- **`browse` needs no headless browser:** implemented with the already-present `httpx` + `beautifulsoup4` (fetch + text extraction). No Playwright/chromium → slim image (build + `/health` smoke verified). JS-rendered pages are not supported (accepted tradeoff; resolves spec §13 risk #7 toward the light path).
- **`gaa.server.__init__`** exposes `create_app` lazily (PEP 562 `__getattr__`) so submodules import before `app.py` exists / without forcing app construction.
- **Action dispatch** aliases `run` ⇄ `run_id`: the agent tool-guide uses `run`, but `status`/`step` handlers read `run_id` while drilldowns read `run` — dispatch fills in whichever is missing so all resolve. Handler tracebacks are logged.
- **Chat loop robustness:** if the LLM returns unparseable JSON (a routine thinking-model failure) the loop still emits a terminal `done` SSE event (no hung stream); a decision that is neither `action` nor `final` is corrected and retried (bounded by `max_iters`) instead of aborting; the `[[gaa:run_id=…]]` marker is only set from a non-error result.
- **Artifact route** is anchored to the runs ROOT (`run_dir.parent == runs_root`), not to a `run_dir` derived from the untrusted `run_id` — verified safe against encoded `..`, encoded slashes, absolute paths, and symlink vectors.
- **Startup** uses a FastAPI `lifespan` handler (not the deprecated `on_event`): `persist.restore(ctx)` (best-effort) then `persona.ensure_seeded(ctx)`.
- **`persist.restore`** treats only `NoSuchKey`/`NoSuchBucket`/`404` as "first boot" (returns False) and re-raises real errors; `snapshot` skips (and warns on stderr) any durable path that would resolve outside the snapshot root.

### Runtime env contract (set at deploy via the `agentbase-deploy` skill — never committed)
- `LLM_BASE_URL` (default MaaS), `LLM_API_KEY`, `LLM_MODEL=google/gemma-4-31b-it` (Gemma 4 for orchestration AND synthesis).
- `PERPLEXITY_API_KEY` (competitor signals), `GAA_BENCHMARK_MODE` (`snapshot`|`crawl`).
- `GAA_AGENT_TOKEN` — Bearer gate for `/chat` + `/invocations` (held server-side by the frontend proxy; leak = RCE, treat as high-sensitivity).
- `GAA_ADMIN_KEY` — gates the dangerous tools (`exec`/`browse`/`self_edit`/mutations); `X-GAA-Admin-Key` header on `/chat`, `admin_key` body field on `/invocations`.
- `VSTORAGE_ENDPOINT` / `VSTORAGE_BUCKET` / `VSTORAGE_ACCESS_KEY` / `VSTORAGE_SECRET_KEY` — persistence; if unset, persistence is a local-only no-op.

### Deploy (via `agentbase-deploy`)
Build `linux/amd64` → push to the managed Container Registry → create a Custom Agent runtime (`/agent-runtimes`, PUBLIC, flavor sized for the analytics deps). The platform only requires `:8080` + `GET /health`.

### Live verification checklist (run after deploy)
1. `GET /health` → 200; runtime ACTIVE.
2. `POST /chat` (Bearer `GAA_AGENT_TOKEN`) with a real "why did <game> drop?" → SSE streams activity + a final ending in `[[gaa:run_id=…]]`.
3. `GET /runs/<id>/report.html` → the full self-contained dossier, byte-exact.
4. A follow-up drilldown reuses the run_id.
5. `POST /invocations` `config_set` without `admin_key` → error; with the key → success.
6. An `exec`/`browse` round-trip via an admin `/chat` session.
7. **Gemma-4 synthesis re-verification:** run a full analysis and confirm the synth stage yields a schema-valid `AttributionHypothesis` (no validation error). If it regresses, set `LLM_MODEL` back to the verified Qwen model for synthesis while keeping Gemma for orchestration (documented fallback, §10/§13).
8. `self_edit` MEMORY.md, redeploy, confirm the edit survived (vStorage restore on boot).

### Operational prerequisites (human, one-time)
- Create a vStorage bucket + S3 access/secret key pair in the VNG Cloud console; set the `VSTORAGE_*` env.
- **Keep** the OpenClaw `gaa` instance for now (live reference for its agent design while building); it is still billed. **Tear it down later** via `/agentbase-teardown` once the Custom Agent is built + verified — do not delete proactively.
