# Game Attribution Agent — GreenNode Claw-a-thon 2026 (Data Analysis track)

An AI analyst that reconstructs the **story behind a game's metric movement**, separating
**internal** causes (your updates, segments, monetization) from **market** causes (genre-wide
trends, seasonality, competitors) — with **dual-axis confidence** (likelihood + evidence quality)
and **every claim cited** to an evidence ledger. It presents scenarios, never decisions, and lowers
confidence honestly when evidence is thin.

> ⚠️ This agent is AI. Outputs are **cited hypotheses with stated assumptions**, not decisions.

## What it does
- **Connect any game's data via chat — no code** (CSV or Roblox dashboard export; an LLM proposes the
  column mapping for you to confirm).
- Ask *"what's going on with my game?"* → it **discovers the most notable recent movement** and runs
  four analysis modules → returns an **interactive HTML report** + a chat summary:
  - **Anomaly** — quantifies the move, finds *when* it broke (change-point) and *how anomalous* (STL).
  - **Segment** — **Adtributor** root-cause: which version/region/cohort drove it, as a citable %.
  - **Market** — **CausalImpact-style counterfactual** vs a genre benchmark → "is it us or the market?"
  - **Competitor & events** — crawled news/social/update signals around the window.
- Output carries the signature **internal-vs-market overlay** chart and a **likelihood × evidence
  confidence matrix**.

## Architecture
LangGraph agent on the GreenNode AgentBase SDK. Graph nodes wrap a deterministic engine
(`adapters → canonical schema → modules → Evidence Ledger → synthesizer → citation validator →
self-consistency gate → HTML report`). The LLM is used only to route intent, map columns, and write
the narrative — it never invents findings. See `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Run locally
```bash
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install -r requirements.txt && pip install -e .
cp .env.example .env   # fill LLM_API_KEY / LLM_MODEL (see Models)
python main.py         # serves on :8080
curl localhost:8080/health
```

## Call it (`POST /invocations`)
```bash
EP=<endpoint-url>
# analyze (after a profile is onboarded)
curl -X POST $EP/invocations -H 'content-type: application/json' \
  -H 'X-GreenNode-AgentBase-Session-Id: s1' -H 'X-GreenNode-AgentBase-User-Id: u1' \
  -d '{"message":"what is going on with my game?"}'
# onboard a data source (chat-assisted, payload-driven)
#   {"action":"onboard_propose","adapter":"roblox|csv","csv_path":"..."}    -> proposed mapping
#   {"action":"onboard_confirm", ...name/platform/genre/adapter/csv_path/mapping...}  -> ingests
```
Returns `{ status, mode, hypothesis, markdown_summary, html }` (the `html` is a self-contained,
offline interactive report).

## Models
Uses the **GreenNode AI Platform (MaaS)**, OpenAI-compatible, model **Qwen 3.5 27B**
(`qwen/qwen3-5-27b`) via `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`. No external (non-MaaS)
provider is used. The deterministic analytics (CausalImpact-style counterfactual, Adtributor,
change-point) run in-process; the LLM only handles routing, column mapping, and narrative synthesis.

## Data
Demo internal data is **aggregate, PII-stripped** game metrics (no customer/confidential data).
External/market data is public (genre benchmark; live Roblox-ecosystem crawl is configurable via
`GAA_BENCHMARK_URL_TMPL` / `GAA_SIGNALS_URL_TMPL`, with a bundled seeded benchmark as the default).

## Deployment (AgentBase Runtime)
- **Runtime:** `gaa` — `runtime-2951893e-745f-40c5-a6d2-66908941f7cb`
- **Flavor:** `runtime-s2-general-2x4` (2 vCPU / 4 GB), PUBLIC, 1 replica
- **Image:** managed Container Registry `vcr.vngcloud.vn/111480-abp111723/gaa`
- **Endpoint:** `https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn`
- Built `linux/amd64`, pushed via `/agentbase-deploy` (`--from-cr`), `--env-file .env`. `GREENNODE_*`
  credentials are auto-injected by the runtime (not in the image or env file).

## Tests
`pytest -q` → 87 passing (TDD throughout; engine verified end-to-end with a fake LLM, deploy verified live).
