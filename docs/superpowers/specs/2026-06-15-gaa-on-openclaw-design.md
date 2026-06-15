# GAA-on-OpenClaw — Design (self-hosted OpenClaw runtime in a Custom AgentBase image)

**Status:** Approved design (pre-implementation; the build is gated on Spike 1, §9).
**Date:** 2026-06-15
**Scope:** Re-host the GAA agent on a **self-hosted OpenClaw runtime**, packaged into **our own Custom Agent Docker image** on GreenNode AgentBase. OpenClaw owns the agent loop, tool-calling, real browser automation, MCP, persona/memory continuity, and sandboxing. GAA shrinks to an **analysis engine exposed over MCP** plus a small HTTP front door that serves the byte-exact dossier and bridges chat.
**Builds on / reuses:** `2026-06-13-gaa-custom-agent-design.md` — the analysis core/CLI/run-dirs/lab/tools, the traversal-safe dossier route, and the vStorage persistence pattern are **reused unchanged**.
**Supersedes / retires:** the homegrown chat loop (`server/agent.py`) from the custom-agent design, and the in-flight `2026-06-15-runtime-loop-hardening-design.md` (branch `feat/runtime-loop-hardening`) — **OpenClaw becomes the hardened loop**, so the typed-registry / native-tool-call / trace work is no longer needed.
**Branch / worktree:** `feat/gaa-on-openclaw`, an isolated git worktree at `…/TestGreenNode-openclaw`, branched from `main`. The `feat/runtime-loop-hardening` branch + its agent are left untouched.

---

## 1. Why this exists (the pivot back, made precise)

On 2026-06-13 the project left OpenClaw and built a custom agent because the **hosted OpenClaw template** could not deliver the 4.58 MB interactive `report.html` to a browser. Re-reading that decision's own evidence (`2026-06-13-gaa-custom-agent-design.md` §1), **every blocker is a property of the locked template, not of OpenClaw itself**:

| Template blocker (2026-06-13) | Why it dissolves when we self-host in our own image |
|---|---|
| `agents.files.get` filename-whitelist rejects nested/large files | We don't use it — the dossier is served by our own HTTP route in the same container |
| chat-exec + base64 garbles bytes | Not a transport anymore — byte-exact `FileResponse` over HTTP |
| `/v1/chat/completions` returns prose only | We control the container; we add routes |
| custom HTTP endpoint "unsupported" (template config exposes only `chatCompletions`) | Our image can listen on any route; AgentBase only requires `:8080` + `GET /health` |
| "modify the template image → impossible" | The image **is ours** |

So self-hosting OpenClaw inside a Custom Agent image is not a return to the thing that failed — it keeps the only piece that ever worked (our own HTTP dossier serving) and swaps the *homegrown loop* for the *real OpenClaw runtime*.

**What that buys us (the requester's stated goals):**
1. **A mature ReAct loop / harness** — adopt OpenClaw's loop instead of hand-rolling and hardening our own.
2. **Real MCP + real browser automation** — the current `browse` is `httpx`+`beautifulsoup4` (no JS); OpenClaw brings genuine browser automation with visual reasoning and native MCP tool integration.
3. **Less to maintain + a real security model** — runtime upkeep, sandboxing, token auth, and prompt-injection defenses move to OpenClaw; our surface shrinks to analysis logic.

Chat channels (WhatsApp/Telegram/Slack) are explicitly **not** a goal — the web frontend stays the interface.

## 2. Goals / non-goals

**Goals**
- One Custom Agent image on AgentBase that runs a **self-hosted OpenClaw daemon** as the runtime, with GAA analysis reachable as **MCP tools**, and the **byte-exact dossier** served over HTTP — preserving the signature artifact-iframe UX.
- Reuse the entire `gaa.core` analysis engine, `gaa.runs` (Run/RunStore/pipeline), the dossier route, `gaa.config`, `gaa.lab`, `gaa.tools_registry`, `gaa.cli`, and the `persist.py` vStorage pattern.
- Persona/self-memory continuity via OpenClaw's native `SOUL.md`/`MEMORY.md`, made durable across redeploys with vStorage.
- A **spike-first** rollout: prove the make-or-break unknowns (esp. OpenClaw × MaaS model compatibility) before building the integration.

**Non-goals**
- Chat channels beyond the web frontend.
- Re-implementing OpenClaw's loop/tool-calling (the whole point is to *not* maintain that).
- Any change to the analysis algorithms, run-dir layout, or dossier rendering.
- Hard multi-tenant isolation (single deployment; sessions scope conversations, unchanged).
- Keeping the `feat/runtime-loop-hardening` work (typed registry / native tool-calls / trace) — superseded by OpenClaw.

## 3. Architecture — container topology

One image, one exposed port (`:8080`), a small supervisor running two top-level processes; the MCP server is an OpenClaw-spawned stdio child:

```
┌─ Custom Agent image (AgentBase Custom Agent runtime, :8080 exposed) ────────┐
│  supervisor (tini/entrypoint) ── starts front door + OpenClaw               │
│                                                                             │
│  Front door  (FastAPI, :8080)  ← the trimmed existing server/app.py         │
│    ├─ GET  /health             → 200 iff front door + OpenClaw both ready    │
│    ├─ GET  /runs/<id>/<art>    → byte-exact dossier (UNCHANGED, tested)      │
│    ├─ POST /chat               → SHIM ⇄ OpenClaw, streams SSE back out       │
│    └─ POST /upload  (CSV)      → onboarding → run (replaces /invocations)    │
│                                                                             │
│  OpenClaw daemon (Node)        ws://127.0.0.1:18789 + WebChat (internal)     │
│    ├─ brain  → MaaS model via OpenAI-compatible base_url (Spike 1)           │
│    ├─ body   → exec · real browser automation · memory                      │
│    └─ MCP client ── spawns ──▶  GAA MCP server (stdio child)                 │
│                                   analyze·segments·detect·market·signals·   │
│                                   synth·report·status·jobs·onboard_*·…       │
│                                   wraps gaa.core via existing actions.py     │
│                                                                             │
│  Shared container FS: RunStore run dirs (report.html, summary.md, …)         │
│  vStorage S3  ◀── snapshot/restore durable subset (persist.py pattern)       │
└─────────────────────────────────────────────────────────────────────────────┘
```

The **front door is the AgentBase contract surface** (`:8080` + `/health`) and the dossier server. **OpenClaw is the runtime.** **GAA is analysis-over-MCP.** The MCP server and front door share the container FS, so the MCP `analyze` tool writes a run dir and `GET /runs/<id>/report.html` serves it — the dossier mechanics are unchanged from the custom-agent design §5.

## 4. Components

### A. OpenClaw daemon (the runtime)
Self-hosted from the open-source distribution, run **headless in the container** (no systemd/LaunchAgent — Spike 2). Configured to:
- point its brain at MaaS via an OpenAI-compatible `base_url` (Spike 1);
- load the **GAA MCP server** from its MCP config (Spike 3);
- load GAA **operating instructions / red-lines** (admin gating, run-id discipline, "use the GAA analysis tools for game questions") as OpenClaw skills/agent instructions;
- seed persona (`SOUL.md`) + self-memory (`MEMORY.md`) from our existing cloned persona.

It owns `exec`, browser automation, memory, the ReAct loop, and tool-calling — so our `server/capabilities.py` (the homegrown exec/browse/self_edit clones) is **dropped**.

### B. GAA MCP server (the seam)
A new thin module that exposes the analysis actions as MCP tools, **wrapping `gaa.core` through the existing `server/actions.py` handlers** — one source of truth per action, reused not rewritten. Tools mirror today's action set: `analyze`, `segments`, `detect`, `market`, `signals`, `synth`, `report`, `status`, `jobs`, `onboard_propose`, `onboard_confirm`, `profile_list`, `profile_use`, `config_get`, `config_set`, `doctor`, `tools_list`, `tools_promote`, `tools_run`. Each tool carries a typed input schema (the typed-registry idea from the loop-hardening spec survives **here**, as MCP tool schemas, rather than in a homegrown loop). Transport: **stdio** (OpenClaw spawns it as a child — the standard MCP pattern), decided/confirmed in Spike 3.

### C. Front door (FastAPI — the trimmed `server/app.py`)
- `GET /health` — returns 200 only when the front door is up **and** the OpenClaw gateway answers (so AgentBase marks ACTIVE only when chat actually works).
- `GET /runs/<id>/<artifact>` — **unchanged**: the traversal-safe, allowlisted dossier route (`report.html`/`summary.md`/`activity.log`/`ledger.jsonl`/`job.json`).
- `POST /chat` — the **shim**: accepts the frontend's `{messages[], active_run_id}` + `X-GAA-Admin-Key`, drives an OpenClaw chat turn, and streams the reply back as the existing SSE event shape (`activity`/`thinking`/`token`/`done`). It also **injects the `[[gaa:run_id=…]]` marker** from the MCP `analyze` tool result rather than trusting the model to echo it (§5).
- `POST /upload` — CSV onboarding from the browser → a run (replaces the old `/invocations` non-chat path).

### D. Persona / self-memory
OpenClaw-native `SOUL.md` + `MEMORY.md` ("your files are your memory"), seeded from the existing cloned persona + GAA red-lines. Self-editing is OpenClaw's, gated by its permission model (§7).

### E. Persistence (reuse `persist.py`)
The container FS is ephemeral and AgentBase Custom Agents can't mount a volume, so the durable subset is tarred to **VNG vStorage (S3-compatible)** on mutation and restored on boot — the exact pattern already built. **Durable subset shifts to OpenClaw's workspace:** OpenClaw config + `SOUL.md`/`MEMORY.md` + skills + MCP config, plus GAA's `gaa.sqlite` (profiles), promoted-tools registry, and `gaa-config.toml`. **Runs are not persisted** (regenerable). Env unchanged: `VSTORAGE_*`; unset ⇒ local-only no-op.

## 5. Data flow

**Chat turn (analysis):** frontend `POST /chat {messages[], active_run_id}` → front-door shim → OpenClaw chat turn → OpenClaw's loop calls the GAA MCP `analyze` tool → MCP server runs `gaa.core` to completion in-process, writes the run dir, returns `{status, run_id, …}` → OpenClaw composes the narrative reply → shim streams `activity`/`thinking`/`token` and, on the terminal event, appends `[[gaa:run_id=<id>]]` from the tool result → `done`.

**Dossier fetch:** frontend detects the marker, strips it, `GET /runs/<id>/report.html` from the front door → sandboxed iframe. (Unchanged from custom-agent §5.)

**Follow-up drilldown:** stateless — `active_run_id` rides in the `/chat` body; the shim/instructions tell OpenClaw to reuse the run for drilldowns instead of starting a fresh analysis.

**CSV onboarding:** frontend `POST /upload` → front door → `onboard_propose`/`onboard_confirm` via the same action handlers → a run the user can then analyze.

## 6. Frontend

**Keep the existing Vercel Next.js frontend; absorb OpenClaw's protocol in the front-door shim.** The frontend's contract is preserved: `POST /chat` with `messages[]` → SSE, then fetch `/runs/<id>/report.html` → sandboxed iframe. The server-side token injection (Next.js route handler holds `GAA_AGENT_TOKEN`, never ships it to the browser) is unchanged. Net frontend change: minimal (the `/invocations` onboarding call becomes `/upload`; everything else is stable).

Rejected alternative: rewire the frontend to speak OpenClaw's WS gateway directly (operator handshake — `Origin` header, `connect.challenge`, protocol 3, scopes). More work, couples the frontend to OpenClaw internals, no benefit while the web UI is the only channel.

## 7. Security posture

OpenClaw's `exec` + browser automation make the agent capable of arbitrary code execution **by design** (same as the custom agent's cloned surface). Reaching it is gated; reading artifacts is open:
- **`/chat` + `/upload` are bearer-gated** (`Authorization: Bearer $GAA_AGENT_TOKEN`, constant-time), held server-side by the frontend proxy — the OpenClaw-gateway-token model. A token leak = RCE on the container; treat as high-sensitivity (rotate via redeploy; `.dockerignore` excludes secrets).
- **Artifact routes are open + read-only + traversal-safe** (`GET /runs/<id>/<artifact>`, `GET /health`).
- **Dangerous/admin actions** (`config_set`, `tools_promote`, `exec`, browser, `self_edit`) gate through **OpenClaw's permission/approval model** plus the `X-GAA-Admin-Key` signal carried by the shim. Exact mechanism (OpenClaw scopes/approvals vs. an MCP-layer admin gate) is confirmed in Spike 3.
- Secrets (`LLM_*`, `PERPLEXITY_API_KEY`, `VSTORAGE_*`, both gate tokens) live only in the runtime env, never in the image.

## 8. Models

OpenClaw's loop quality depends on the model's native tool-calling **through OpenClaw, over MaaS**. The model bake-off already scoped for loop-hardening (**Gemma 4 31B-IT / MiniMax M2.5 / Qwen 3.5 27B**) is folded into Spike 1: pick the model that (a) OpenClaw can drive via `base_url` and (b) tool-calls most reliably within acceptable latency. Model choice is a config change (`LLM_MODEL`), not code. Synthesis keeps the verified Qwen path unless a candidate is re-verified to emit schema-valid `AttributionHypothesis` (the custom-agent §10 gate still applies).

## 9. Gating spikes (run FIRST; the build is gated on Spike 1)

Throwaway probes, no production code, mirroring the project's spike-first culture. **Ordered by make-or-break.**

1. **OpenClaw × MaaS model compatibility *(make-or-break — task 1)*.** Can OpenClaw drive a MaaS model via an OpenAI-compatible `base_url` + key? Run the bake-off (Gemma 4 31B / MiniMax M2.5 / Qwen 3.5 27B) against `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` and score tool-call reliability + latency. **If no candidate works, the approach fails here** — fall back to the custom-agent + loop-hardening path.
2. **OpenClaw headless in a container.** Runs as a plain foreground process (no systemd/LaunchAgent), survives in `python:slim`-class image, reachable by the front-door shim.
3. **MCP discovery + dispatch.** OpenClaw loads the GAA MCP server (stdio) and the chosen model reliably calls `analyze` with valid args and consumes the result. Confirms the admin-gating mechanism too.
4. **Dossier coexistence + shim round-trip.** Front door serves `/runs/<id>/report.html` on `:8080` alongside OpenClaw, and the `/chat` shim ⇄ OpenClaw streams SSE end-to-end (incl. marker injection).

Each spike records a go/no-go + the concrete config that worked (folded into the plan before building).

## 10. Reuse vs. retire

**Reused unchanged:** `gaa.core` (analytics/modules/synth/render/schema/adapters/crawl/sources/store/onboarding/llm), `gaa.runs`, `gaa.config`, `gaa.lab`, `gaa.tools_registry`, `gaa.cli`, the `GET /runs/<id>/<artifact>` route, `persist.py` (re-targeted at the OpenClaw workspace subset).

**New:** the GAA MCP server module; the front-door shim (`/chat` ⇄ OpenClaw) + `/upload`; the container supervisor + Dockerfile (Node OpenClaw + Python GAA); OpenClaw workspace seed (config, `SOUL.md`/`MEMORY.md`, skills/red-lines, MCP config).

**Retired:** `server/agent.py` (homegrown loop), `server/capabilities.py` (exec/browse/self_edit — now OpenClaw's), the hand-maintained tool guide in `server/persona.py`, and the entire `feat/runtime-loop-hardening` line of work.

## 11. Testing

- `gaa.core` suite stands unchanged (the engine doesn't move).
- **MCP server:** tool input-schema validation (valid args pass; missing/wrong-type rejected), envelope of results, dispatch against fixture runs — the loop-hardening registry tests transplant here.
- **Front door:** dossier route behavior is already covered (traversal cases); add shim SSE shaping (incl. marker injection from a scripted MCP result) and `/upload` onboarding.
- **Persistence:** snapshot/restore round-trip of the OpenClaw-workspace durable subset against a stubbed S3 (the existing moto/fake-client pattern).
- **OpenClaw loop quality** is validated by the spikes + live verification, not unit tests (it's third-party).

## 12. Key decisions

| Decision | Alternative | Why |
|---|---|---|
| Self-hosted OpenClaw in our own image | hosted OpenClaw template | only a self-hosted image can serve the dossier (the 2026-06-13 blockers were all template constraints) |
| Deploy as a Custom Agent on AgentBase | local/VPS daemon | keeps the Claw-a-thon platform alignment; AgentBase only needs `:8080` + `/health` |
| GAA as an **MCP server** | exec-skills; keep FastAPI custom agent as a service | typed/robust seam; uses OpenClaw's native MCP (a stated goal); reuses `actions.py` handlers |
| Keep frontend + `/chat` shim | rewire to OpenClaw WS gateway | preserves the dossier-iframe UX with minimal change; web is the only channel |
| Retire the homegrown loop + loop-hardening | finish loop-hardening | OpenClaw *is* the hardened loop — finishing both is duplicated effort |
| Reuse `persist.py` → vStorage | AgentBase Memory; volume | no volume on Custom Agents; pattern already built + tested |
| Spike-first, gated on MaaS compat | build then test | OpenClaw × MaaS is the make-or-break unknown; cheap to disprove early |
| Shim injects the run-id marker | model echoes it | robust to the model forgetting; deterministic |

## 13. Risks / open items

1. **OpenClaw × MaaS compatibility (highest).** Mitigated by Spike 1 as task 1; explicit fallback = the existing custom-agent + loop-hardening path (kept on `feat/runtime-loop-hardening`).
2. **Image weight + multi-process container.** Node (OpenClaw) + Python (GAA) + a browser stack for OpenClaw's automation = a heavier image and a supervisor. Measure in Spike 2; size the flavor up if needed.
3. **Shim ⇄ OpenClaw protocol.** OpenClaw may expose an HTTP/WebChat backend easier to bridge than the raw WS gateway; Spike 4 picks the simplest reliable transport. Risk: SSE streaming fidelity (activity/thinking/token) through the bridge.
4. **Admin gating semantics.** Mapping our two-level (agent token + admin key) onto OpenClaw's permission/approval model needs Spike 3 confirmation; fallback is an MCP-layer admin gate keyed off the shim-passed admin signal.
5. **OpenClaw upgrade churn.** Self-hosting means pinning + maintaining an OpenClaw version; "less to maintain" is net-true (we drop the loop) but not zero. Pin a version; document the bump procedure.
6. **Persistence granularity / memory drift.** Same coarse whole-subset tarball + self-evolving-memory poisoning risks as the custom-agent design §13.8–9; same mitigations (snapshots are recoverable; consider a MEMORY.md size cap).
7. **Synthesis model regression** if synthesis moves off the verified Qwen path — gated by re-verification (§8).

## 14. What needs confirming before planning

The two requester-facing decisions are **resolved** (frontend = keep + shim; spikes-first, gated on Spike 1). No open questions block planning. Spikes 1–4 are the first plan phase; the integration build is conditional on Spike 1 passing.
