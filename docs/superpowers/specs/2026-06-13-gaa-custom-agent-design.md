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

**Non-goals**
- OpenClaw (retired from the architecture).
- Hard multi-tenant isolation (one deployment; sessions scope conversations, not data — unchanged).
- Real-time/streaming data ingestion (batch, unchanged).

## 3. Architecture

A single Docker image (Custom Agent runtime), a **FastAPI app on port 8080**. We use FastAPI (not the `greennode-agentbase` SDK's `/invocations`-only entrypoint) because we need custom routes — notably the dossier GET route. Routes:

| Route | Purpose |
|---|---|
| `POST /chat` | The conversational agent loop. SSE streaming. Stateless (client sends `messages[]`). |
| `POST /invocations` | Structured analysis API (programmatic + the frontend's non-chat paths, e.g. CSV onboarding). |
| `GET /runs/<run_id>/<artifact>` | Serves a run's `report.html` / `summary.md` / `activity.log` / `ledger.jsonl` **byte-exact over HTTP**. |
| `GET /health` | 200 when ready (platform marks runtime ACTIVE). |

All requests resolve the shared `GaaContext` (the Plan-1 `build_context` composition root) once at startup; handlers run the `gaa` pipeline/stores/registry **in-process**.

## 4. The chat agent loop (`/chat`)

A **full agent loop run in our code** — replicating what OpenClaw's agent did, but in-process so tool results are byte-exact (no garbling). **Stateless:** the frontend sends the full `messages[]` (OpenAI style); the loop runs over that history each request.

**Manual JSON tool-loop** (not native function-calling — the MaaS Qwen endpoint's tool support is unverified and quirky):
1. A system prompt lists the available **actions** and instructs the model to reply with **either** `{"action": "<name>", "args": {…}}` **or** `{"final": "<narrative>"}` (parsed by the existing tolerant `_extract_json`).
2. If an action: **dispatch it in-process** against `GaaContext` (the same logic the CLI commands use), append the result as a tool message, loop. Bounded at a max iteration count (e.g. 8) to prevent runaway loops.
3. If `final`: that narrative is the assistant reply.

**Exposed actions** (the `gaa` toolbox, in-process): `analyze`, `segments`, `detect`, `market`, `signals`, `synth`, `report`, `status`, `jobs`, `onboard_propose`, `onboard_confirm`, `profile_list`, `profile_use`, `config_get`, `config_set`, `doctor`, `tools_list`, `tools_promote`, `tools_run`. Admin-class actions (`config_set`, `onboard_confirm`, `profile_use`, `tools_promote`, `tools_run`) are gated (see §7).

**Analysis runs to completion in-process.** When `analyze` is invoked, the handler advances the run through all stages synchronously (`pipeline.advance(run, deadline=None)` — the budget/step machinery existed only for OpenClaw's exec timeout; in a FastAPI request we just run it). Synthesis uses the real MaaS LLM. The loop then emits a final narrative ending with the marker:

```
[[gaa:run_id=<run_id>]]
```

**Active run for follow-ups:** stateless — the run_id is in the conversation history (the prior assistant turn's marker). The system prompt instructs the model to reuse it for drilldowns (`segments --run <id>`, `synth --run <id>`). No server-side session store.

**Streaming (SSE):** the final narration streams token-by-token; lightweight activity events ("running segment analysis…") stream as the loop dispatches actions, so the UI shows progress. (Internal tool-decision LLM calls are not streamed.)

## 5. Dossier delivery (the whole point)

The frontend detects the `[[gaa:run_id=…]]` marker, strips it from the visible text, and fetches `GET /runs/<id>/report.html` from the **same Custom Agent endpoint** → renders it in a **sandboxed iframe** (`sandbox="allow-scripts"`, `srcdoc`/blob) — Claude's exact artifact mechanism. Byte-exact HTTP handles the 4.58 MB self-contained Plotly dossier directly. The analysis pane may also fetch `summary.md` / `activity.log` / `ledger.jsonl` for a live trace. The route reads from the run store (`RunStore.path_for`), restricted to files under `data/.../runs/<id>/` (no path traversal).

## 6. Persistence — vStorage S3 (real durability)

The Custom Agent filesystem is ephemeral and the runtime can't mount a volume, so durable state is persisted to **VNG vStorage** (S3-compatible object storage; endpoint e.g. `https://hcm04.vstorage.vngcloud.vn`, HTTPS, boto3).

- **`src/gaa/persist.py`** — a small layer with `restore()` and `snapshot()`:
  - **`restore()`** (called at server startup): pulls the latest state tarball from the bucket and extracts it into the workspace.
  - **`snapshot()`** (called after each durable mutation — `onboard_confirm`, `tools_promote`, `config_set`): tars the **durable subset** and puts it to the bucket.
- **Durable subset:** `data/tools/` (promoted-tool registry), `gaa-config.toml`, `gaa.sqlite` (profiles), and the metrics Parquet dir. **Runs are NOT persisted** (regenerable; a redeploy loses old run dossiers, which a re-ask reproduces — keeps the snapshot small).
- **Implementation:** boto3 S3 client against the vStorage endpoint; generalizes the Plan-2c `tools_registry.export/import` tarball pattern to whole-durable-state. New dependency: `boto3`.
- **Config (env):** `VSTORAGE_ENDPOINT`, `VSTORAGE_BUCKET`, `VSTORAGE_ACCESS_KEY`, `VSTORAGE_SECRET_KEY`. If unset, persistence is a no-op (local-only) — so tests + local dev need no S3.
- **Net:** runtime-grown toolbox + config + onboarded games survive redeploys/restarts — OpenClaw-parity durability, without a volume.

**Prerequisite (one-time, human):** create a vStorage bucket + an S3 access/secret key pair in the VNG Cloud console; put them in the runtime's env.

## 7. Security posture

- Public endpoint (matches the pre-teardown design; it's a demo/hackathon entry).
- **Analysis is open** (`/chat` analysis questions, drilldowns, dossier reads).
- **Admin-class actions are gated** by a constant-time `admin_key` check against env `GAA_ADMIN_KEY` (re-introduced for the public endpoint): `config_set`, `onboard_confirm`, `profile_use`, `tools_promote`, `tools_run`. In `/chat`, an admin session is signalled by a header/marker the frontend sets for admin users; the structured `/invocations` admin actions require the key in the payload. With `GAA_ADMIN_KEY` unset, admin actions are refused. (Documented as soft, demo-grade — the hardening path is real auth.)
- vStorage keys + LLM keys live only in the runtime env (never in the image; `.dockerignore` excludes `.env`/secrets).

## 8. Reuse vs. new code

**Reused unchanged** (Plans 1–2c): `gaa.core` (analytics/modules/synth/render/schema/adapters/crawl/sources/store/onboarding/llm), `gaa.runs` (Run/RunStore/pipeline), `gaa.config`, `gaa.lab`, `gaa.tools_registry`, `gaa.cli` (the CLI stays — standalone use + a shared action layer).

**New:**
```
src/gaa/
├── server/
│   ├── __init__.py
│   ├── app.py        # FastAPI app + routes (/chat, /invocations, /runs/<id>/<artifact>, /health)
│   ├── agent.py      # the manual JSON tool-loop + SSE
│   └── actions.py    # action-name → in-process handler map (shared with the CLI command fns)
├── persist.py        # vStorage S3 snapshot/restore
Dockerfile            # python:3.11-slim + gaa + fastapi/uvicorn/boto3, serves :8080
```
To avoid duplicating logic, the analysis/onboarding/admin actions are factored into `gaa/server/actions.py` (or a shared `gaa.actions`) that **both** the CLI commands and the chat loop call — one source of truth per action.

**New deps:** `fastapi`, `uvicorn`, `boto3`.

## 9. Deployment

- **Dockerfile**: `python:3.11-slim`, `pip install -e .` (+ fastapi/uvicorn/boto3), `CMD` runs uvicorn serving `gaa.server.app:app` on `:8080`.
- Build `linux/amd64`, push to the managed Container Registry (`vcr.vngcloud.vn/111480-abp111723/gaa`), deploy as a **Custom Agent runtime** (`/agent-runtimes`, PUBLIC, 1 replica, flavor ~`runtime-s2-general-2x4`).
- Runtime env: `LLM_*`, `PERPLEXITY_API_KEY`, `GAA_BENCHMARK_MODE`, `GAA_ADMIN_KEY`, `VSTORAGE_*`.
- `GET /health` → ACTIVE. Endpoint URL is public.
- **OpenClaw `gaa` instance is deleted** (no longer part of the architecture — ends its billing). Plan 3's `openclaw_install.py` + `workspace/` skill files are retired (kept on history; the gaa skill content informs the chat loop's system prompt).

## 10. Testing

- **Offline (pytest):** the agent loop tested with `FakeLLM` scripted to emit specific tool-decisions then a final (deterministic, no network); the action dispatch tested against fixture runs; dossier routes tested via FastAPI TestClient against a fixture run dir; `persist.py` tested against a stubbed/in-memory S3 (moto or a fake client) for snapshot/restore round-trip; the Plans 1–2c suite (248) stands.
- **Live:** deploy the Custom Agent; verify `/health`, `/chat` → analysis → marker, `GET /runs/<id>/report.html` returns the dossier, a follow-up drilldown, an admin-gated action with/without the key, and a vStorage snapshot/restore across a redeploy.

## 11. The frontend (separate spec, next)

Clone `vercel/ai-chatbot`, gut NextAuth/Postgres to single-user, point chat at `POST /chat` (the Custom Agent) via a Next.js server route, detect the `[[gaa:run_id=…]]` marker → fetch `GET /runs/<id>/report.html` → sandboxed iframe (the artifacts pane), with a live trace from the other run artifacts. CSV onboarding uploads via `POST /invocations`. Designed in its own brainstorming cycle after this backend spec is approved.

## 12. Key decisions

| Decision | Alternative | Why |
|---|---|---|
| Custom Agent host | OpenClaw template | only a Custom Agent can serve the interactive dossier (spikes proved OpenClaw can't) |
| FastAPI app | restore the SDK `/invocations` shell | need custom GET routes (dossier); contract only requires :8080 + /health |
| Full in-process agent loop | deterministic router | in-process tool results are byte-exact; replicates OpenClaw's UX without its fragility (user choice) |
| Manual JSON tool-loop | native function-calling | MaaS Qwen tool support unverified + quirky; manual loop is robust + matches existing `_extract_json` |
| Stateless (client history) | server session store | matches the frontend + OpenAI style; conversation is the single source of truth; no state to wipe |
| vStorage S3 persistence | AgentBase Memory; volume; ephemeral | Memory is conversational (not files); no volume mount on Custom Agents; S3 cost is negligible and gives real durability (user choice) |
| Persist setup-state only (not runs) | persist everything | keeps snapshots small; runs are regenerable |
| Re-introduce `admin_key` | open admin | the endpoint is public; gate state-changing actions |

## 13. Risks / open items

1. **MaaS function-calling / JSON reliability** — mitigated by the manual JSON loop + tolerant parsing + bounded iterations; verify live that Qwen reliably emits the action JSON.
2. **In-process analysis latency** — a full analyze (crawl + N synth samples + render) in one request is ~10–30 s; SSE streams progress so the UX isn't a blank wait. If too slow, revisit async.
3. **vStorage snapshot granularity** — whole-durable-state tarball after each mutation is coarse; fine at low write frequency; per-file sync is a later optimization.
4. **Dossier size** — 4.58 MB inline Plotly loads fine over HTTP; if it grows, switch `report.html` to CDN-Plotly (smaller) — a `render` change, not an architecture change.
5. **`show_thinking`** (deferred from the combine) — now trivially feasible (the server can stream synthesis reasoning); revisit in implementation.
