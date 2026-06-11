# Game Attribution Agent — Design Spec

**Date:** 2026-06-10
**Context:** GreenNode Claw-a-thon 2026 (VNG internal AI hackathon)
**Track:** Data Analysis
**Submission deadline:** 17/06/2026 12:00 · **Voting:** 22/06–03/07 · **Winner:** community vote

---

## 1. Summary

A Python agent, deployed on AgentBase, that reconstructs **the story behind a game's metric movement** and separates **internal causes from market-wide ones**. Given a game and a metric movement (e.g. "revenue dropped 25% in May"), it returns an **Attribution Hypothesis**: the core story, an internal-vs-market cause breakdown with cited evidence, 2–4 next-scenarios, and risks — every claim tagged on **two independent confidence axes** and traceable to a source. It **presents scenarios, never prescribes decisions**, and **lowers confidence honestly** when evidence is thin rather than fabricating.

Output is an **interactive HTML report with charts**. Any game team can **set up their own data input via chat (no code)** — the agent works across platforms through a canonical-schema + adapter design, with Roblox fully wired for the hero demo.

This spec covers the hackathon MVP, scoped to win on a focused, visceral, verifiable demo.

---

## 2. Goals & non-goals

### Goals
- Diagnose a real metric movement and produce an Attribution Hypothesis (backward-looking diagnosis).
- Mechanically separate **internal** vs **market/external** causes.
- Express **dual confidence** on every claim: *likelihood* (how probable) and *evidence quality* (how well-supported), never collapsed into one number.
- Ground every claim in a traceable source via an **Evidence Ledger**; degrade confidence + state gaps when evidence is missing.
- Render an **interactive HTML report** with charts (the votable artifact).
- Let any team **self-serve their data input** via chat-assisted onboarding (CSV + Roblox adapters), platform-agnostic by design.
- Deploy on AgentBase and be judge-callable (satisfies the pass/fail criteria).

### Non-goals (explicitly out of scope for the hackathon)
- ❌ Forward-looking potential/investment evaluation (brief use case #2).
- ❌ Structured external benchmarks for non-Roblox platforms (generic web-search/crawl fallback instead).
- ❌ Dedicated platform adapters beyond **CSV** and **Roblox** (CSV covers other platforms via export).
- ❌ Custom frontend beyond the HTML report + AgentBase chat.
- ❌ Real-time/streaming data, model fine-tuning, macro/financial sources (World Bank etc.).
- ❌ Multi-game portfolio management (architecture is game-agnostic; one active profile at a time is enough).

**Stretch (only if ahead of schedule):** Roblox Open Cloud live Analytics API; a macro/seasonality module; a second worked example game.

---

## 3. Constraints (hackathon reality)

- **Timeline:** ~6.5 working days (training 10/06 → submit 17/06 12:00). Submit early.
- **Infra:** AgentBase, code-based deploy; OpenClaw instances 2 vCPU / 4 GB RAM each → keep data snapshots small, image lean.
- **Models:** MaaS Gemma-4-31B-IT / Qwen-3-27B; external models (Claude/OpenAI) allowed **at team cost** and **must be declared in README**.
- **Budget:** 10,000,000 VND POC wallet (expires after competition).
- **Data rules:** public / synthetic / **anonymized** data only — **no PII, no confidential data.** Declare data sources in README.
- **Winner = community vote** → the demo video, the visible "wow," and relatability to VNG game-people voters matter as much as the engineering.
- **Pass/fail (all required):** (1) agent running on AgentBase, judges can make ≥1 successful request; (2) valid 2–3 min demo video; (3) complete README + form (≤300 chars), no placeholders.

---

## 4. User & hero use case

**User:** a game PM / BI / producer who sees a metric move and needs to know *why* and *what's likely next* — fast, evidence-backed, without a data-science team.

**Hero use case (backward diagnosis):** *"Our game's [metric] moved — is it us (an update, a segment, a bug) or the market (genre-wide, seasonal, a competitor)?"* The agent answers with an Attribution Hypothesis it can defend with citations.

**Hero demo subject:** the team's **own Roblox game** (real dashboard access). Internal data is real (aggregate, anonymized); external/market data is real public Roblox-ecosystem data. The agent **discovers the most notable recent movement from the data** (scan mode) and diagnoses it — demonstrating autonomy.

---

## 5. Architecture

### 5.1 Two modes, one orchestrator

```
                 ┌──────────────────────────────┐
   user intent → │  ORCHESTRATOR (router)        │
                 └──────┬────────────────┬───────┘
              "connect  │                │  "what happened
               my data" │                │   to my game?"
                        ▼                ▼
              ┌──────────────┐    ┌──────────────────────┐
              │ SETUP MODE   │    │ ANALYSIS MODE         │
              │ onboarding/  │    │ attribution engine    │
              │ profiling    │    │ (modules → ledger →   │
              │              │    │  synth → report)      │
              └──────────────┘    └──────────────────────┘
```

The router classifies intent (onboard a source vs analyze) and checks whether an active `GameProfile` exists. Setup mode produces/updates a profile; analysis mode consumes it.

### 5.2 Data-input abstraction (platform-agnostic seam)

```
   Team raw data (any platform)
        │
        ▼
┌──────────────────────────────┐
│  ADAPTER (per source type)    │
│  • Generic CSV (+ mapping)    │   normalizes →
│  • Roblox (dashboard export)  │
└──────────────┬───────────────┘
               ▼
   CANONICAL METRICS SCHEMA          ← all modules read ONLY this
   {date, metric, value,
    dims:{platform,region,version,
          cohort,device,source,...},
    meta}
```

Modules never see raw platform data — only the canonical schema. Adding a platform later = one new adapter, no module changes.

### 5.3 Analysis engine (the attribution flow)

```
Orchestrator (parse → {game, metric, timeframe, direction}; pick modules)
        │  dispatch (parallel)
   ┌────┼─────────────┬────────────────┐
   ▼    ▼            ▼                ▼
[INTERNAL]  [INTERNAL]   [EXTERNAL]      [EXTERNAL]
Anomaly     Segment      Market          Competitor &
Detection   Decomp.      Benchmark       Event Signals
   └────────┴────────────┴────────────────┘
        │  each writes structured findings →
        ▼
   EVIDENCE LEDGER  (single source of truth for all claims)
        │
        ▼
   SYNTHESIZER (LLM)  — every claim must cite a ledger id;
        │              validator drops/flags uncited claims;
        │              assigns dual confidence
        ▼
   REPORT RENDERER  — Jinja2 + Plotly (charts from ledger data, not LLM text)
        │
        ▼
   API response: { html, hypothesis (JSON), markdown_summary }
```

---

## 6. Components

Each component is an independently testable unit. For each: purpose · interface · dependencies.

### 6.1 Adapters
- **Purpose:** normalize a platform's raw data into the canonical metrics schema.
- **Interface:** `Adapter.load(raw_source, mapping) -> CanonicalMetrics (DataFrame)`. Two implementations: `CSVAdapter`, `RobloxAdapter`.
- **Depends on:** pandas; a column `mapping` (from onboarding).

### 6.2 GameProfile store
- **Purpose:** persist a team's setup: `{game_name, platform, genre, column_mapping, external_source_config, created_at}`.
- **Interface:** `save(profile)`, `get(active)`, `list()`. Backed by sqlite/JSON.

### 6.3 Onboarding / Profiling (Setup mode)
- **Purpose:** turn an uploaded CSV / Roblox export into a confirmed mapping + GameProfile, via chat, no code.
- **Flow:** ingest sample → LLM proposes a `column → canonical` mapping from column names + sample rows → present to user → user confirms/corrects in chat → save profile.
- **Interface:** `propose_mapping(sample) -> mapping`; `confirm(mapping) -> GameProfile`.
- **Depends on:** Adapters, GameProfile store, LLM.

### 6.4 Orchestrator (router + planner)
- **Purpose:** classify intent (setup vs analysis), parse analysis queries into `{game, metric, timeframe, direction}` (or trigger scan mode if open-ended), select which modules to run.
- **Interface:** `route(query) -> Mode`; `plan(query, profile) -> [modules]`.
- **Depends on:** LLM, GameProfile store.

### 6.5 Analysis modules (4) — research-backed methods
Each: `run(profile, query_context) -> [LedgerEntry]`. The methods below replace naive deltas with established attribution techniques; see **§15** for the research basis, citations, and 4GB footprint notes.
1. **Internal · Anomaly Detection** — confirm/quantify the movement, **locate *when* it broke** via change-point detection (`ruptures` PELT), and gauge **how anomalous** via STL seasonal-trend decomposition (statsmodels) + an expected-vs-actual deviation band. The detected onset feeds the Market module's intervention point. **Scan mode:** when no metric is specified, surface the most salient recent movement.
2. **Internal · Segment Decomposition** — **Adtributor** (Microsoft NSDI'14): scores each dimension/element by *explanatory power* (contributions that sum to 100% → a citable % per segment in the ledger), *succinctness*, and *surprise* (Jensen-Shannon divergence). Handles **ratio KPIs (ARPU, retention rate)**, not just additive counts. (HotSpot = additive-only drill-down; BALANCE = non-additive, Tier-2.)
3. **External · Market Benchmark** — **CausalImpact / Bayesian structural time-series** (statsmodels `UnobservedComponents`): builds a *counterfactual* of your KPI from genre/comparator control series, so the reported effect is the **internal-specific deviation after the market is absorbed** — the rigorous form of "is it us or the market," with a credible interval. Falls back to indexed comparison when control history is too sparse to fit.
4. **External · Competitor & Event Signals** — crawled/cached: competitor launches/updates, the game's own update log, news, social-sentiment spikes around the window. (RAG claims grounded; defensibility via the abstention gate in §8.)

### 6.6 Evidence Ledger
- **Purpose:** single source of truth for every assertable fact; the anti-hallucination mechanism.
- **Entry:** `{id, module, claim, value, source, source_type: internal|external|derived, strength: high|med|low, timeframe}`.
- **Interface:** `add(entry) -> id`; `all() -> [entry]`. `strength` is computed (see §8).

### 6.7 Synthesizer + citation validator
- **Purpose:** compose the Attribution Hypothesis from the ledger; enforce traceability.
- **Rule:** every claim in the output references ≥1 ledger id. The **validator** checks each claim maps to a ledger entry and **drops/flags uncited claims**.
- **Interface:** `synthesize(ledger, query_context) -> AttributionHypothesis`; `validate(hypothesis, ledger) -> AttributionHypothesis`.
- **Depends on:** LLM (structured output via Pydantic schema), ledger.

### 6.8 Report Renderer
- **Purpose:** turn the hypothesis JSON + ledger data into a self-contained interactive HTML report. **The LLM never writes HTML; charts are drawn from ledger data, not LLM text.**
- **Charts:**
  1. Headline time-series with the anomaly window shaded.
  2. Segment decomposition waterfall/bar (where internally it came from).
  3. **Internal-vs-Market overlay** (indexed to 100) — the core-USP "money chart."
  4. **Dual-confidence matrix** — 2-axis grid (x = evidence quality, y = likelihood), each cause/scenario plotted — visualizes the signature USP.
- **Interface:** `render(hypothesis, ledger, series) -> html_str`.
- **Depends on:** Plotly (inline JS, self-contained), Jinja2.

### 6.9 API service + deployment
- **Purpose:** expose the agent on AgentBase, judge-callable.
- **Interface:** `POST /analyze -> {html, hypothesis, markdown_summary}`; setup endpoints for onboarding; optional `GET /report/{id}`.
- **Depends on:** FastAPI, Docker, AgentBase.

---

## 7. Data strategy

| Layer | Source | Feeds | Compliance |
|---|---|---|---|
| **Internal** | Roblox Creator Dashboard export (DAU/MAU, D1/D7 retention, revenue/ARPPU, acquisition, demographics by age/platform/device/region) → CSV/JSON snapshot | modules 1, 2 | own game, aggregate, no PII; declared in README; absolute revenue may be indexed/normalized for the public video |
| **External (live)** | Public crawl: RoMonitor/Rolimon's (CCU/visits for own + similar games), Roblox Discover/trending, r/roblox, YouTube/TikTok/Discord buzz, update logs/comments | module 4 | public data only |
| **Benchmark** | Curated public Roblox genre/ecosystem trend series, seeded ahead of time | module 3 | public summaries |

- **Ingestion:** primary = CSV/JSON export snapshot (reliable). Stretch = Roblox Open Cloud Analytics API if it covers the metrics.
- **Crawl-reliability:** every crawl result is written to a **cache snapshot**; the demo and judge-calls replay from cache if a live fetch is slow/blocked. Live crawl refreshes the cache opportunistically.
- **Non-Roblox platforms:** internal via generic CSV adapter; external via web-search/crawl fallback (lower, honestly-stated evidence quality).

---

## 8. Output: dual-confidence model & schema

### Dual confidence (the USP, made rigorous)
- **Likelihood** *(how probable is this the real story / will it happen)* — `Very likely · Likely · Possible · Unlikely`. LLM-reasoned, constrained to ledger evidence.
- **Evidence quality** *(how solid is the support)* — `Strong · Moderate · Weak`. **Computed by rule** from the ledger:
  - number of independent supporting entries,
  - source-type agreement (internal **and** external aligned = stronger),
  - source-reliability weight (official/dataset > news > social),
  - recency & window coverage.

Both axes always shown, never merged: `"Likely · Moderate evidence"` ≠ `"Possible · Strong evidence"`.

### Self-consistency abstention gate (anti-hallucination)
Before a hypothesis is returned, the headline + primary-cause direction (internal vs market) are sampled N=3× and their agreement scored (self-consistency). Low agreement **downgrades the headline evidence quality one notch and adds an explicit gap note** instead of asserting a shaky story — a lightweight form of **conformal abstention** (DeepMind 2024), which bounds the error rate; it plugs directly into the evidence-quality axis. The *formal* conformal guarantee (calibrated on a labeled corpus of past KPI movements) and **TRAQ** retrieval-correctness for the external RAG modules are Tier-2 (§15). *Note: multi-agent LLM debate was evaluated and **rejected** — research shows no reliable factuality gain (§15).*

### `AttributionHypothesis` schema
```
{
  main_story:        str,                       # 1–2 sentence core narrative
  confidence:        {likelihood, evidence_quality},
  causes: {
    internal: [ {claim, evidence_ids[], likelihood, evidence_quality} ],
    market:   [ {claim, evidence_ids[], likelihood, evidence_quality} ]
  },
  scenarios: [ {description, likelihood, evidence_quality, signals_to_watch[]} ],  # 2–4
  risks:     [ {description, likelihood, evidence_quality} ],
  evidence:  [ {id, claim, value, source, source_type, strength} ],   # the ledger
  assumptions_and_gaps: [str]                   # honest "what we couldn't verify"
}
```

### Rendered example (condensed — illustrative of the *format*; the actual hero demo is the Roblox game)
> **Game X · Revenue −25% (May 2026)**
> Most of the drop is **internal, not market-wide** — a retention dip in the v3.2 update among SEA new-installs drove the bulk; the genre was roughly flat. — *Likely · Moderate evidence*
> **🔵 Internal (primary)** *Likely · Strong*: D7 retention for v3.2 new-installs 18%→11% `[L2]`; SEA new-install revenue −40% `[L3]`, coinciding with the May 4 v3.2 release `[L7]`.
> **🟠 Market (largely ruled out)** *Possible · Moderate*: same-genre top-20 flat (−3%) `[L9]`; no industry downturn `[L10]`.
> **Scenarios:** (1) hotfix recovers ~15–20% in 2–3 wks *Likely · Moderate* — watch D1/D7 of v3.3 cohort; (2) competitor Y SEA push `[L12]` → drop persists *Possible · Weak* — watch SEA install share.
> **Assumptions/gaps:** no UA-spend data → can't rule out an acquisition cut.

---

## 9. Reliability & fallbacks (demo-critical)

- **Crawl-cache replay** — a live fetch never blocks a run.
- **LLM fallback** — external (Claude) → MaaS (Gemma/Qwen) if the key/endpoint is unavailable.
- **Pre-baked snapshot** of the hero analysis as a guaranteed-good run for the video; live calls still work.
- **Graceful degradation is on-brand** — a missing source → the module logs a "data gap" → evidence quality drops + an honest assumptions/gaps line, instead of failing.
- **De-risk deploy on Day 1** — push a hello-world container to AgentBase before building features.

---

## 10. Demo (2-act, 2–3 min video)

- **Act 1 — "any team, no code":** connect a data source (Roblox + a quick CSV from another platform) → agent proposes the mapping in chat → confirmed. Proves generality.
- **Act 2 — the payoff:** "what's going on with my game?" → agent discovers the notable movement → opens the HTML report: internal-vs-market overlay, segment waterfall, dual-confidence matrix, honest gaps line.
- **Closing beat:** "Give scenarios, not solutions — the human decides." Reinforces trust + the inviolable principle.

---

## 11. Tech stack

- **Python 3.11**; deployed via the **GreenNode AgentBase SDK** (`GreenNodeAgentBaseApp`, port 8080) — platform shell + LangGraph orchestration per **Plan 0**.
- **LangGraph** orchestrator (graph nodes = modules; ledger = graph state; multi-turn memory) — supersedes the earlier "thin custom orchestrator / not LangGraph" note.
- **Pydantic** for ledger + hypothesis schemas + structured LLM output + the citation validator.
- **LLM:** GreenNode AI Platform **MaaS** (OpenAI-compatible, via `langchain-openai`); external Claude/OpenAI optional + declared.
- **Analytics:** pandas + duckdb; **statsmodels** (STL + `UnobservedComponents` causal counterfactual); **ruptures** (change-point); **Adtributor** implemented in-house (light).
- **Crawler:** reuse `DataCrawler` (httpx/BeautifulSoup; Playwright only if needed) → sqlite/JSON cache.
- **Report:** Plotly (inline self-contained JS) + Jinja2.

> **4GB footprint:** use the statsmodels-based causal counterfactual, **not** the TensorFlow CausalImpact port; avoid Prophet (cmdstan) — STL covers seasonality. statsmodels + ruptures + in-house Adtributor are all light. See §15.

---

## 12. 7-day plan & parallelization

**Streams:** **A** Data & Crawler · **B** Agent core (lead) · **C** Renderer + Deploy + Demo.

| Day | Milestone |
|---|---|
| 1 (10/06) | Training; finalize spec; repo skeleton + Pydantic schemas; **hello-world deployed to AgentBase**; A starts Roblox export + adapter interface |
| 2 (11/06) | A: internal store + CSV/Roblox adapters + crawler MVP + cache · B: orchestrator + mode-routing + Anomaly + Segment modules + GameProfile store · C: chart prototypes + HTML template + FastAPI skeleton |
| 3 (12/06) | A: benchmark + competitor/event crawl · B: Market + Competitor modules + Evidence Ledger + chat-assisted mapping · C: 4 charts wired to ledger + confidence matrix |
| 4 (13/06) | B: synthesizer + dual-confidence + citation validator · C: full HTML report end-to-end · **first full pipeline run on hero case** |
| 5 (14/06) | Integrate + tune prompts/confidence; lock hero narrative (scan-mode discovery); **full agent deployed + judge-callable** |
| 6 (15/06) | Hardening, fallbacks, edge cases; README + form (≤300 chars); demo video draft |
| 7 (16/06) | Buffer; final video; **submit early** |

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| AgentBase deploy surprises | Deploy hello-world Day 1; keep image lean |
| Crawl flakiness / blocking | Cache-replay; pre-baked snapshot; web-search fallback |
| Small-model unreliability | External Claude for orchestration/synthesis; MaaS fallback |
| LLM hallucinated confidence/claims | Evidence Ledger + citation validator + rule-based evidence quality |
| Scope creep (onboarding + analysis in 7 days) | CSV+Roblox adapters only; thin chat-mapping; parallel streams |
| Data-rule compliance (own game data) | Aggregate only, strip PII, optional revenue indexing, declare in README |

---

## 14. Open questions (verify at/after training)

- Does AgentBase let the container serve an extra route (`GET /report/{id}`) or only a fixed invoke contract? (HTML self-contained path works regardless.)
- Does Roblox Open Cloud expose the needed analytics, or is CSV export the only reliable path? (CSV export is the baseline.)
- RoMonitor/Rolimon's access method — public API vs scrape; rate limits. (Cache mitigates.)
- External model cost/latency from AgentBase egress vs MaaS. (Declare; fallback ready.)

---

## 15. Analytical rigor — methods, footprint & roadmap (research-backed)

From a verified deep-research pass (25 sources, adversarially fact-checked). Tier-1 folds into the engine now (see **Plan 2A**); Tier-2 is post-hackathon. Implemented as LangGraph nodes; the Evidence Ledger + dual-confidence model are unchanged.

### Tier-1 (ship-now)
| Module / layer | Method | What it adds | Key caveat |
|---|---|---|---|
| Market | CausalImpact / BSTS counterfactual ([Brodersen 2015](https://arxiv.org/abs/1506.00356)) via statsmodels `UnobservedComponents` | rigorous "is it us or the market" + credible interval + time-varying effect | controls must be **unaffected by your update**; sparse history → fall back to indexed comparison |
| Segment | Adtributor ([Microsoft NSDI'14](https://www.usenix.org/conference/nsdi14/technical-sessions/presentation/bhagwan)) — EP (sums to 100%) + succinctness + JS-divergence surprise | ratio-KPI (ARPU/retention) root-cause; a citable % contribution per segment → ledger | derived-measure surprise assumes measure independence |
| Anomaly | change-point (`ruptures` PELT) + STL decomposition + deviation band | *when* it broke + *how anomalous* vs expected | seasonality needs ≥1–2 cycles of history |
| Confidence | self-consistency abstention (lightweight [conformal abstention](https://arxiv.org/pdf/2405.01563), DeepMind 2024) | bounded over-claiming; feeds the evidence-quality axis | formal guarantee is *marginal* + needs a calibration corpus (Tier-2) |

### Tier-2 (roadmap)
- **BALANCE** ([SIGMOD'23](https://arxiv.org/pdf/2301.13572)) — non-additive, missing-data-tolerant RCA.
- **Demeaned synthetic control** ([Ferman & Pinto 2021](https://onlinelibrary.wiley.com/doi/full/10.3982/QE1596)) — mitigates a *proven* SC/DiD bias.
- **Forecasting / what-if simulation** — Uber Orbit, Meta Kats, LinkedIn Greykite, Netflix Surus.
- **Formal conformal + TRAQ** ([NAACL'24](https://arxiv.org/pdf/2307.04642)) — calibrated guarantees once a labeled corpus of past KPI movements exists.
- **ThirdEye-style** unified monitoring + proactive alerting + interactive drill-down ([LinkedIn/StarTree](https://github.com/startreedata/thirdeye)).
- **PyRCA** ([Salesforce](https://github.com/salesforce/PyRCA)) — graph-based RCA backbone once we build a game-KPI causal graph.

### Rejected (do NOT build)
- **Multi-agent LLM debate** as the anti-hallucination layer — research-refuted (no reliable factuality gain). Prefer conformal + retrieval grounding.

### Honest caveats (these *reinforce* "scenarios, not decisions")
- **Domain-transfer gap:** these RCA methods were validated on IT/AIOps/ad metrics, not game KPIs — they transfer as *techniques*; we build the game-KPI segment/causal structure ourselves and do not trust borrowed accuracy figures.
- **Causal-validity gap:** every counterfactual estimator is only as valid as its assumptions (control independence, good pre-period fit), imperfect for real games — which is exactly *why* outputs stay **cited hypotheses with stated assumptions**, never decisions.
