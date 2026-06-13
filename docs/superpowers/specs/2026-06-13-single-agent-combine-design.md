# GAA Single-Agent Combine — Design

**Status:** Approved design (pre-implementation)
**Date:** 2026-06-13
**Supersedes:** the two-agent architecture in `technical-design.md` (v. 2026-06-12, preserved on `archive/full-history`)
**Context docs:** `docs/REBUILD-PRIVATE.md` (rebuild runbook, private), original design spec (2026-06-10), OpenClaw integration spec (2026-06-12) — both on `archive/full-history`

---

## 1. Summary and motivation

The Game Attribution Agent (GAA) previously ran as **two** platform resources: a custom AgentBase runtime (Docker image, HTTP `/invocations` endpoint) and an OpenClaw chat agent (`gaa-chat`) that called it over curl. Both were deleted on 2026-06-13. This design combines them into **one OpenClaw instance**: the GAA code lives in the agent's workspace and runs via the exec shell — no Docker image, no HTTP endpoint, no second resource.

The combine is not just consolidation. It adopts the architecture of a modern coding agent (Claude Code) deliberately:

1. **The LLM orchestrates; deterministic tools produce facts.** (Already the old system's core commitment — evidence ledger + citation validator — now extended to the whole surface.)
2. **Files are ground truth; state is always re-discoverable.** No state lives only in the model's memory or an opaque store.
3. **Tiered tool surface:** a golden-path command for the common case, composable primitives for follow-ups, and ad-hoc generated code as the escape hatch.
4. **Progressive-disclosure instructions:** a short SKILL.md with reference docs loaded on demand.

There is no deadline constraint on this design; it optimizes for the best long-term system, not the fastest rebuild.

## 2. Goals and non-goals

### Goals

- One platform resource (a single OpenClaw instance) runs everything.
- The chat agent can answer follow-up questions cheaply (re-run one module against existing evidence) and novel questions by writing code — capabilities the two-agent split made impossible.
- All analysis state (jobs, evidence, traces, reports) is inspectable files; any confusion is recoverable by re-listing reality.
- Live progress streaming to the UI: pipeline activity, accumulating evidence, and (opt-in) the synthesis model's real thinking.
- A frontend with Claude-UI-grade UX: chat, thinking display, file upload, artifacts/analytics pane.
- The trust chain survives: every number in a dossier traces to a ledger entry; the citation validator stays the hard gate.

### Non-goals

- Multi-tenant isolation (unchanged from before; one workspace per deployment).
- Real-time/streaming data ingestion (batch exports, as before).
- Prescriptive recommendations (scenarios and signals-to-watch, not decisions).
- Unsupervised self-extension — tool promotion (§6, Tier 2.5) is in scope but always admin-initiated; the agent never promotes tools on its own judgment.

## 3. Code strategy: fresh shell, salvaged core

The old codebase has two layers with opposite fates:

- **Salvaged as-is (the deterministic core):** `analytics/` (PELT change-point, Adtributor, BSTS counterfactual), `modules/`, `synth/` (self-consistency gate, citation validator), `schema/`, `adapters/`, `crawl/`, `sources/`, `render/`, `llm/`, `onboarding/`, and the Profile/Metrics/Benchmark stores. Research-backed, 216-test-covered, transport-agnostic. Imported from `archive/full-history` into the new skeleton, untouched except imports.
- **Written fresh (the orchestration shell):** everything that existed because GAA was a remote HTTP service — replaced by a CLI-first design.
- **Deleted, never ported:** AgentBase SDK app (`main.py`), `GraphAgent` (`graph.py`), the deterministic intent router (`orchestrator/router.py` — the OpenClaw agent *is* the router now; `planner.py` survives inside the plan stage), payload-dispatch `admin_actions.py`, `JobStore`/`jobs.sqlite`, SQLite `ConfigStore`, `Dockerfile`, `greennode-agentbase` and `langgraph` dependencies.

New repository layout (built on the empty fresh `main`):

```
src/gaa/
├── core/        # salvaged library (packages listed above)
├── runs/        # NEW: run-directory model (replaces jobs/)
├── lab.py       # NEW: sanctioned data API for ad-hoc agent code (Tier 3)
├── cli/         # NEW: one module per subcommand; the only entry point
└── config.py    # NEW: gaa-config.toml load/validate
workspace/       # files installed into the OpenClaw workspace
├── AGENTS.md
└── skills/gaa/  (SKILL.md + references/)
scripts/
└── openclaw_install.py   # idempotent installer (replaces openclaw_bootstrap.py)
tests/
```

## 4. System architecture

```
┌─ Browser ───────────────────────────────────────────────┐
│  Next.js app (cloned from vercel/ai-chatbot, gutted):   │
│  chat + thinking blocks + uploads + artifacts pane      │
└───────────────┬────────────────────────┬────────────────┘
                │ chat (SSE)             │ /gaa/* routes
┌───────────────▼────────────────────────▼────────────────┐
│  Next.js route handlers = the proxy (token server-side) │
│  • /openclaw/* → chat completions passthrough           │
│  • /gaa/*      → gateway WS: allowlisted exec + reads   │
└───────────────┬────────────────────────┬────────────────┘
                │                        │
┌─ OpenClaw instance (the ONLY platform resource) ────────┐
│  Chat agent (Qwen 3.5 27B via MaaS)                     │
│   ├ skills/gaa/SKILL.md + references/   (instructions)  │
│   ├ AGENTS.md                           (red-lines)     │
│   └ exec ─→ gaa CLI ─→ core library                     │
│                          │                              │
│  Workspace files = ground truth:                        │
│   data/runs/<run_id>/…      gaa-config.toml             │
│   data/{metrics,benchmark}  gaa.sqlite (profiles)       │
│   data/tools/ (promoted)    .env (secrets, red-lined)   │
└─────────────────────────────────────────────────────────┘
External: MaaS LLM (Qwen 3.5 27B) · SteamCharts · Roblox trackers · Perplexity sonar (opt-in)
```

Two consumers drive the same CLI: the chat agent via exec, and the browser via the proxy's allowlisted gateway calls. All shared state is files both can see.

**Trust chain (unchanged, one level down):** deterministic tools → `ledger.jsonl` → synthesizer → citation validator → dossier.

## 5. The run directory (replaces the job system)

Every analysis is a directory:

```
data/runs/2026-06-13-revenue-drop-k3f9/
├── job.json        # stage, status, query, session, plan state (metric, window, direction)
├── ledger.jsonl    # append-only; one LedgerEntry per line, streamed as modules write
├── activity.log    # ts | stage | message   (the "thinking trace")
├── thinking.md     # opt-in: synthesis model's reasoning, labeled per sample
├── summary.md      # written at render
├── report.html     # written at render (self-contained dossier)
└── scratch/        # Tier-3 ad-hoc scripts + their saved outputs
```

- **Run IDs are human-readable slugs** (`YYYY-MM-DD-topic-suffix`). The old system had a live incident where the orchestrator confused backgrounded-process names with job ids; self-describing ids plus `gaa jobs` (re-list reality from disk) make that failure class recoverable instead of fatal.
- **`ledger.jsonl` streams**: modules append entries the moment they produce them, so the UI shows evidence accumulating live mid-run — impossible with the old blob-in-SQLite job model.
- **Concurrency:** the chat agent and the UI proxy can both poke a run, so every advance takes an `flock` on the run directory; a concurrent second caller gets current status instead of double-advancing.
- The **5-stage resumable pipeline** (plan → crawl → modules → synth → render) survives conceptually intact: fixed stage order, per-call budget, the at-least-one-stage-per-call guarantee (an expired budget still advances exactly one stage, so progress is monotonic), stage exceptions mark the run `error` with the message preserved. Only persistence changes: from SQLite blobs to these files. Cleanup is `gaa jobs --prune` (age-based) instead of a store TTL.
- **Budget default ~20 s per exec slice** (`GAA_STEP_BUDGET_S`), tuned to stay under OpenClaw's exec-backgrounding threshold rather than the dead platform's 50 s request close.

## 6. The CLI surface (three tiers)

One executable, `gaa`. Output is compact JSON on stdout by default (the primary readers are an LLM and a proxy); `--text` renders human-readable.

### Tier 1 — Golden path (the rails)

```
gaa analyze "why did revenue drop last week?" [--session s] [--budget 20]
gaa step <run_id>          # advance one budget slice (≥1 stage guaranteed)
gaa status <run_id>        # pure read — never advances
gaa jobs [--session s] [--prune]
```

`analyze` creates the run dir, advances until budget, prints `{run_id, stage, status, done}`. Splitting mutating `step` from read-only `status` is new (the old poll always advanced): the proxy drives progress with `step`; anything can `status` safely.

### Tier 2 — Primitives (drilldowns against an existing run's ledger)

```
gaa detect   --run <id> [--metric dau]            # change-point + seasonal z-score
gaa segments --run <id> [--dimension region]      # Adtributor
gaa market   --run <id>                           # BSTS counterfactual vs genre
gaa signals  --run <id> [--query "..."]           # web/competitor crawl
gaa synth    --run <id> "follow-up question"      # re-synthesize from current ledger
gaa report   --run <id>                           # re-render html + md
```

Each primitive reads the run's window/profile from `job.json`, **appends** provenance-tagged findings to `ledger.jsonl`, and prints them. A follow-up like "which region drove it?" is one fast command instead of a full re-run; a follow-up `synth` produces an updated, citation-validated hypothesis from the enriched ledger. The ledger becomes a growing case file per investigation.

**Honesty note:** when the agent narrates a primitive's printed output directly in chat (without `synth`), the citation validator is not in the loop; the guarantee is that the evidence is verbatim in the conversation. The dossier always goes through synth + validator.

### Tier 3 — Ad-hoc analysis code (the escape hatch)

GAA installs as an importable library (`pip install -e .`), and `gaa.lab` is a small facade purpose-built for generated code:

```python
from gaa import lab
df = lab.load_metrics("my-game")          # canonical long-format DataFrame (a copy)
bench = lab.load_benchmark("idle-rpg")    # genre trend series (a copy)
lab.add_evidence(run_id, claim=..., value=..., source="adhoc:scratch/01-arpu-split.py")
```

When no module covers the question (e.g. "compare weekend vs. weekday ARPU since the break"), the agent writes a short script, runs it, and reads the output. Guardrails:

1. **Scripts are run artifacts:** generated code lives in `runs/<id>/scratch/NN-name.py` with saved output — auditable and re-runnable.
2. **Read-only data access:** `lab` loaders return copies; `AGENTS.md` forbids writing to the stores. Bad generated code yields a traceback, not corrupted data.
3. **Honest provenance:** `lab.add_evidence` tags entries `adhoc:` and caps their evidence strength at *Moderate* — deterministic, reviewed modules outrank one-shot generated code by policy. Ad-hoc findings then flow into a re-`synth`ed dossier with full citations.
4. **Rails in `references/adhoc.md`:** when to drop to code, the `lab` API, the scratch convention, "print numbers and quote them verbatim; never report a number you didn't print."

**Stated caveat:** Qwen 3.5 27B writes markedly weaker code than a frontier model; Tier 3's value scales with the orchestrator model and improves for free when the platform upgrades it. The tiering is the mitigation — the agent escalates downward only when the tier above doesn't fit.

### Tier 2.5 — Tool promotion (the toolbox that grows)

When a Tier-3 scratch script proves useful, an admin asks the agent to keep it:

```
gaa tools promote --run <id> --script scratch/01-arpu-split.py --name arpu-split \
    --description "Split a metric by weekend vs weekday over the run window"
gaa tool run arpu-split [--run <id>] [--args …]
gaa tools list | show <name> | remove <name> | sync-docs | export | import <tarball>
```

Promotion **copies** (freezes) the script into a registry:

```
data/tools/arpu-split/
├── tool.py        # frozen copy of the scratch script, parameterized
└── tool.toml      # name, description, args schema, md5, provenance:
                   #   source run + script, promoted-by session, date
```

- **Discoverability closes the loop:** `gaa tools sync-docs` regenerates `references/tools.md` from the registry, and the SKILL.md escalation path becomes analyze → primitives → **promoted tools** → fresh scratch code ("before writing new scratch code, check `gaa tools list`").
- **Promotion buys reuse, not authority.** Promoted-tool ledger entries are tagged `tool:<name>` and stay capped at *Moderate* evidence strength. The trust hierarchy is explicit: shipped modules (Strong-capable; reviewed + tested in the repo) > promoted tools (Moderate; frozen and reused, never human-reviewed) > one-shot scratch (Moderate, `adhoc:`). The upgrade path to Strong is a human porting the tool into `core/modules` with tests — the system grows its toolbox, not its own trustworthiness.
- **Guardrails:** promote/remove are admin-red-lined; promoted tools obey all Tier-3 rules (`gaa.lab` only, read-only data, numbers printed and quoted verbatim). `tool run` verifies the recorded md5 before executing — a drifted or tampered script refuses to run rather than silently producing different numbers.
- **Stated limitation:** the registry is workspace state and is wiped on instance recreate, like profiles and config. Mitigations: `gaa tools export/import` (a tarball an operator can pull through the gateway), and the installer re-imports a backed-up registry if present.

### Operations

```
gaa onboard propose --csv <path> [--adapter csv|roblox]
gaa onboard confirm --csv <path> --mapping <json> --name --platform --genre
gaa profile list | use <name>
gaa config get [key] | set <key> <value>
gaa doctor
```

`gaa doctor` replaces `/health`: checks Python deps (statsmodels/ruptures import), MaaS reachability, store paths, config validity. It is the installer's verification workhorse and the early test of the load-bearing risk (can the template image run the pipeline?).

## 7. Configuration as a visible file

`gaa-config.toml` in the workspace root replaces the SQLite ConfigStore:

```toml
[benchmark]
mode = "crawl"                  # snapshot | crawl

[sources]
steam_series_url_tmpl = "https://…"
# roblox_*, signals_* …

[synthesis]
n_samples = 3
show_thinking = false           # true → write runs/<id>/thinking.md

[behavior]
instructions = ""               # appended to synthesis prompt, ≤2000 chars
```

- Resolution order unchanged: **file → env → default**. Sources and the synthesizer resolve config per run, so changes take effect on the next analysis without restarts.
- `gaa config set` validates on write (enum/URL checks); a hand- or agent-edited file is validated at load with a precise error.
- **Secrets never live here.** `LLM_API_KEY`, `PERPLEXITY_API_KEY`, etc. stay in `.env`, which `AGENTS.md` red-lines. Config and secrets no longer share a store, so the old masking machinery disappears.
- Behavior changes ("answer in Vietnamese from now on") become auditable one-line file diffs — and trivially reversible before a demo.

## 8. LLM usage

| Call site | Model | Purpose |
|---|---|---|
| Chat orchestration | Qwen 3.5 27B (OpenClaw's own loop) | route intent, sequence `gaa` commands, narrate |
| `onboarding/profiler` | MaaS Qwen 3.5 27B | propose `ColumnMapping` from 20 sample rows |
| `synth/synthesizer` | MaaS Qwen 3.5 27B × N samples | ledger + question → `AttributionHypothesis` JSON |
| `crawl/perplexity` | Perplexity `sonar` (opt-in) | qualitative market trend + signals, with citations |

Synthesis calls keep `enable_thinking: False` by default for fast clean JSON; with `synthesis.show_thinking = true`, the client requests thinking and captures `reasoning_content` into `runs/<id>/thinking.md`, labeled per sample (N concurrent samples means N labeled traces, not one monologue). The deterministic intent router is deleted — the chat agent's skill instructions are the router, which is how a coding agent decides between its tools.

## 9. Skill and instruction structure (progressive disclosure)

```
workspace/
├── AGENTS.md                     # red-lines, always loaded
└── skills/gaa/
    ├── SKILL.md                  # < 1 page: decision guide + conventions
    └── references/
        ├── analysis.md           # analyze/step/status/jobs recipes, [[gaa:run_id=…]] marker
        ├── drilldowns.md         # the six primitives, when each applies
        ├── tools.md              # promoted tools — auto-generated by `gaa tools sync-docs`
        ├── adhoc.md              # Tier-3 rails: lab API, scratch convention, verbatim-numbers rule
        ├── onboarding.md         # propose → confirm flow, CSV handling
        └── admin.md              # config/profile/tools-promote commands
```

`SKILL.md` decision guide: fresh question → `analyze`; follow-up about an existing run → a primitive; no primitive fits → check `gaa tools list` for a promoted tool; still nothing → Tier-3 code per `adhoc.md`; unsure what runs exist → `gaa jobs`; never invent a run id. Reference files hold exact command lines, loaded only when doing that task — keeping the orchestrator's context small and its rails tight.

`AGENTS.md` red-lines: admin commands (`config`, `profile use`, `onboard confirm`) only for sessions whose user id starts with `admin:`; never read `.env` aloud or edit it; never fabricate run ids; always use budgeted forms (`analyze --budget` / `step`), never unbounded runs; Tier-3 scripts never write to data stores.

## 10. Frontend

**Base: a clone of `vercel/ai-chatbot`** (Next.js + AI SDK), which already renders all four requirements Claude-style: streaming chat, collapsible reasoning blocks, file attachments, and an artifacts side panel. Built fresh on the `gaa-test-frontend` repo's empty `main` (old code on `archive/full-history`).

Modifications:

- **Gut:** NextAuth multi-user auth → single-user mode; Postgres-backed document/artifact persistence → deleted (our artifacts are workspace files).
- **Chat:** AI SDK pointed at the OpenClaw `/v1/chat/completions` passthrough route (OpenAI-compatible). If the template's SSE exposes reasoning deltas, the existing reasoning UI renders the chat model's thinking with zero extra work (10-minute probe at rebuild time; no design dependency on it).
- **Artifacts pane → analysis pane:** repointed at run-dir polling. During a run: live `activity.log`, streaming `ledger.jsonl` entries, `thinking.md` when enabled. On completion: `report.html` in a sandboxed iframe, `summary.md` as text.
- **Uploads:** the attachment flow feeds the onboarding route (below).
- The old Live/Local toggle and Vite proxy are gone.

## 11. The proxy contract (Next.js route handlers)

The gateway token lives only server-side. Routes:

| Route | Transport | Does |
|---|---|---|
| `/openclaw/*` | HTTP SSE passthrough | chat completions, user-scoped sessions; `admin:` prefix convention for admin sessions |
| `POST /gaa/step` `{run_id}` | gateway exec | `gaa step <validated-id>` → status JSON; the UI's polling driver |
| `GET /gaa/run/<id>/<artifact>` | gateway file read | only `job.json`, `ledger.jsonl`, `activity.log`, `thinking.md`, `summary.md`, `report.html` |
| `POST /gaa/onboard` | gateway exec + file write | stage CSV into workspace tmp; run `onboard propose` / `confirm` |

The proxy is a **strict allowlist**: exactly two exec shapes (with run-id validation) and file reads only under `data/runs/`. It never forwards arbitrary commands. Flow after a chat question: agent replies with `[[gaa:run_id=…]]` → UI strips the marker → polls `/gaa/step` → renders live trace/evidence → on `done`, fetches `report.html` and `summary.md`.

## 12. Installer

`scripts/openclaw_install.py` — idempotent, replaces the endpoint-era bootstrap. Order matters; the load-bearing risk goes first:

1. Connect to the gateway WS (spike-verified handshake: `Origin` header matching the instance host, protocol 3, `role:"operator"` with operator scopes, `openclaw-control-ui` client id).
2. Exec `git clone`/`pull` of the GAA repo into the workspace.
3. Create the Python env and `pip install -e .` — **first real step because it tests whether the template image can run the pipeline at all** (statsmodels/ruptures). If not, stop and rethink (known options: vendor wheels, or a custom template).
4. Write `.env` (from the private runbook §4) and seed `gaa-config.toml`.
5. Install `AGENTS.md` + skill files — chat-driven md5-verified writes where the files API whitelist blocks direct writes.
6. Verify: `gaa doctor`, then a budget-bounded smoke `analyze`.

Every step checks state before acting; re-running after drift is the recovery path. Known exec-shell gotchas honored: POSIX `sh` (no `source`; use `.`), long commands get backgrounded (hence small budgets), headerless callers get defaulted session/user.

## 13. Error handling and reliability

- **CLI:** every subcommand catches exceptions and prints structured `{"status":"error","error":…}` JSON with a nonzero exit code; the agent and proxy both get parseable failures.
- **Pipeline:** stage exceptions mark the run `error` with message preserved (unchanged).
- **Resumability:** every stage boundary persists to the run dir; a container restart loses at most the in-flight stage (unchanged).
- **Benchmark tiers:** unchanged — snapshot floor always present; crawl and Perplexity tiers additive, never load-bearing. Perplexity remains opt-in via key presence and keeps the string-citation normalization fix.
- **Analytics fallbacks:** unchanged — short series → simple z-score; thin pre-period → indexed comparison; each labels its evidence as weaker.
- **Run-id confusion:** recoverable by construction (`gaa jobs` + readable slugs).
- **Lock contention:** second concurrent `step` returns current status instead of blocking or double-advancing.

## 14. Security posture

- The gateway token grants full operator access; it exists only in the Next.js server env. The proxy's allowlist (two exec shapes, run-dir-only reads) is the narrowed surface.
- Admin/user separation remains **soft** (AGENTS.md instructions keyed on the `admin:` session prefix), as before and documented as such. The old payload `admin_key` is dropped: there is no network API to guard anymore; anyone with exec on the workspace is already an operator. The hardening path (a second, admin-only instance) is unchanged and still deferred.
- `.env` is the secrets boundary inside the workspace, enforced by red-lines (instruction-level, not mechanical — stated honestly).
- Tier-3 scripts run with workspace privileges; the read-only-stores rule is convention plus `lab`'s copy-returning API, not a sandbox.

## 15. Testing

- **Salvaged core:** the existing test suite (FakeLLM and all) comes across nearly untouched.
- **New unit/integration tests:** run-directory persistence (create/advance/resume via the expired-deadline trick, error marking, prune); lock contention (two concurrent `step`s → one advances, one reports); CLI contract tests per subcommand (JSON shapes, in-process runner); config file validation; `gaa.lab` (loaders return copies; `add_evidence` tags and caps strength); tools registry (promote/list/remove CRUD, md5 verification refuses a drifted script, `sync-docs` regeneration, `tool:` ledger provenance, export/import round-trip).
- **Live-verified (not unit-tested):** the installer and the gateway proxy, as before. Scripted E2E in the demo runbook: chat question → marker → step-poll → live trace → dossier; plus a Tier-3 drilldown ("weekend vs weekday ARPU") → re-synth → updated dossier; plus an admin config change by chat reflected in `gaa-config.toml`.

## 16. Documentation plan

This spec is the design of record for the combined system. After implementation, `docs/technical-design.md` is rewritten as-built: §§5–9 of the old doc (pipeline stages, analytics methods, ledger/trust chain, data layer, LLM usage) carry over largely intact since the core is salvaged; §§3–4, 10–11, 15 (architecture, API, admin, OpenClaw integration, deployment) are replaced wholesale by this design. The old version remains readable on `archive/full-history`.

## 17. Key decisions and trade-offs

| Decision | Alternative considered | Why this way |
|---|---|---|
| Single OpenClaw instance, code in workspace, exec transport | keep two agents; localhost daemon + curl | one resource, no daemon babysitting; exec slices map cleanly onto the existing resumable pipeline |
| Step-per-exec CLI | one-shot full-run exec | full runs take minutes and hit the exec-backgrounding gotcha; budget slices keep acks fast and progress monotonic |
| Fresh shell + salvaged core | port whole repo / full rewrite | the orchestration layer is obsolete by design; the analytics core is the verified, hardest-won asset |
| Run directories (files) over SQLite jobs | keep JobStore | re-discoverable state, live streaming to the UI, human-inspectable, fixes the fabricated-id failure class |
| Three-tier tool surface | monolith pipeline only / free-form primitives only | rails for the weak orchestrator's main flow; flexibility where it pays; audit trails where it's risky |
| Config as a TOML file | SQLite ConfigStore | visible, auditable, agent-editable with validation; secrets separated into `.env` |
| Delete the deterministic intent router | keep it in front of the CLI | the chat agent is the router now; SKILL.md is its routing table |
| Drop payload `admin_key` | keep it | no network API remains; exec access already implies operator; soft role split documented |
| Clone `vercel/ai-chatbot` | assistant-ui composition; LibreChat adoption | Claude-parity UX on day one with all four requirements rendered; rewiring data plumbing is lower-risk than re-owning UX design |
| Evidence-strength cap on `adhoc:` entries | treat all evidence equally | one-shot generated code should not outrank reviewed deterministic modules in a cited dossier |
| Tool promotion buys reuse, not trust | promoted tools earn higher evidence strength | frozen-but-unreviewed code stays Moderate; the path to Strong is human review into `core/modules` with tests |

## 18. Risks and open questions

1. **Template image capability** — if the OpenClaw container can't install/run statsmodels + ruptures, the plan needs a rework (vendor wheels or custom template). Tested at installer step 3, before anything else is built on it.
2. **Orchestrator quality** — Qwen 3.5 27B may misroute or write poor Tier-3 code. Mitigations: tiered rails, re-discoverable state, audit-trail scratch scripts; improves for free with platform model upgrades.
3. **Chat-model thinking over SSE** — unknown whether the template exposes reasoning deltas; probe at rebuild, no design dependency.
4. **Gateway file-read API shape** — the proxy assumes the gateway can read workspace files (or falls back to exec `cat`); verify during the proxy spike.
5. **Workspace wipe on instance recreate** — unchanged operational fact; data re-onboarding remains a runbook step after every recreate.

## Future directions (explicitly out of scope)

- A second, admin-only OpenClaw instance as the role-separation hardening path.
- Multi-game portfolio views in the analysis pane.
