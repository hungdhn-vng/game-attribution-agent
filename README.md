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
A self-contained FastAPI **Custom Agent** deployed on GreenNode AgentBase (its own image:
`/chat` agent loop, `/invocations`, `/runs/<id>/<artifact>` dossier, `/health`). `/chat` is a
hand-rolled JSON tool-calling loop (one decision per turn) that drives a resumable analysis
pipeline (`plan → crawl → modules → synth → render`) wrapping a deterministic engine:
`adapters → canonical schema → modules → Evidence Ledger → synthesizer → self-consistency gate →
citation validator → HTML report`. The LLM (an OpenAI-compatible MaaS model via `langchain-openai`)
is used only to route intent, map columns, and write the narrative — it never invents findings.
See `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Run locally
```bash
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install -r requirements.txt && pip install -e .
cp .env.example .env   # fill LLM_API_KEY / LLM_MODEL (see Models)
uvicorn gaa.server.app:app --port 8080   # serves on :8080 (same entrypoint as the Dockerfile)
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

## Async analyze (job + poll)

Analysis runs as a **resumable async job** across up to five pipeline stages
(`plan → crawl → modules → synth → render`).  Each `/invocations` call
advances the job as far as the per-request budget allows, then suspends.

**Start / continue an analysis**
```bash
# First call — starts a new job and runs the first stage(s)
POST /invocations  {"message": "what is going on with my game?"}
# Response (may not be done yet):
{
  "status": "success", "mode": "analyze",
  "job_id": "abc123", "job_status": "running",
  "stage": "crawl", "activity": "...", "done": false
}

# Poll until done
POST /invocations  {"action": "analyze_status", "job_id": "abc123"}
# When done:
{
  "status": "success", "done": true,
  "hypothesis": {...}, "markdown_summary": "...", "html": "..."
}
```

The `GAA_REQUEST_BUDGET_S` env var controls how long each call is allowed to
run before it suspends (default 40 s).  Set `GAA_N_SAMPLES` to control
self-consistency sampling (default 3).

## Live market benchmark

Benchmark data comes from three tiers, applied in order:

1. **Snapshot floor** (always on) — `src/gaa/data/seed/benchmark_snapshot.json`
   is seeded into the benchmark store on every cold start.  It ensures
   `genre_trend` never returns empty even if crawl is disabled or offline.
   Rebuild the snapshot against live trackers with:
   ```bash
   python scripts/build_benchmark_snapshot.py
   ```
2. **Quant crawl** (opt-in, `GAA_BENCHMARK_MODE=crawl`) — `RobloxBenchmarkProvider`
   and `SteamBenchmarkProvider` hit the configured tracker URL templates
   (`GAA_ROBLOX_DISCOVER_URL_TMPL`, `GAA_ROBLOX_SERIES_URL_TMPL`,
   `GAA_STEAM_DISCOVER_URL_TMPL`, `GAA_STEAM_SERIES_URL_TMPL`) to fetch live
   CCU / player-count series for comparator games.
3. **Perplexity web tier** (opt-in, `PERPLEXITY_API_KEY=pplx-...`) — if the quant
   crawl yields insufficient data, `WebSearchBenchmarkProvider` queries the
   **Perplexity sonar** model for a qualitative trend summary with citations.

## Models
- **GreenNode AI Platform (MaaS)** — OpenAI-compatible, model **Qwen 3.5 27B**
  (`qwen/qwen3-5-27b`) via `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`.  Used for intent
  routing, column mapping, and narrative synthesis.
- **Perplexity (external, web tier)** — `sonar` model via `PERPLEXITY_API_KEY`, used only when
  `GAA_BENCHMARK_MODE=crawl` and the quant providers return insufficient data.  Disabled by
  default; leave `PERPLEXITY_API_KEY` blank to never call Perplexity.

The deterministic analytics (CausalImpact-style counterfactual, Adtributor, change-point) run
in-process; the LLM only handles routing, column mapping, and narrative synthesis.

## Data
Demo internal data is **aggregate, PII-stripped** game metrics (no customer/confidential data).
External/market data is public (genre benchmark; live Roblox/Steam crawl is configurable via
`GAA_BENCHMARK_MODE=crawl` + URL templates, with a bundled snapshot as the default floor;
`GAA_SIGNALS_URL_TMPL` enables live competitor signals).

## Deployment (AgentBase Runtime)
- **Runtime:** `gaa` — `runtime-2951893e-745f-40c5-a6d2-66908941f7cb`
- **Flavor:** `runtime-s2-general-2x4` (2 vCPU / 4 GB), PUBLIC, 1 replica
- **Image:** managed Container Registry `vcr.vngcloud.vn/111480-abp111723/gaa`
- **Endpoint:** `https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn`
- Built `linux/amd64`, pushed via `/agentbase-deploy` (`--from-cr`), `--env-file .env`. `GREENNODE_*`
  credentials are auto-injected by the runtime (not in the image or env file).

### Sensor Tower (optional)
| Env var | Required | Default | Notes |
|---|---|---|---|
| `GAA_ST_BASE_URL` | No | `https://stg-aawp-connector.vnggames.net/sensor-tower-v2` | Sensor Tower MCP server URL |
| `GAA_ST_REDIRECT_URI` | **Yes** (if using Sensor Tower) | — | Public Vercel callback, e.g. `https://game-attribution-agent.vercel.app/api/sensor-tower/callback`. Must **exactly** match the OAuth client's registered redirect_uri. |

The frontend needs **no new env vars** — it already uses `GAA_BACKEND_URL` + `GAA_AGENT_TOKEN` to relay the OAuth callback server-to-server.

## Tests
`pytest -q` → 177 passing (TDD throughout; engine verified end-to-end with a fake LLM, deploy verified live).
