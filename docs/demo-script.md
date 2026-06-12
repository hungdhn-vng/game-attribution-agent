# Demo script (2–3 min video)

Endpoint: `https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn`
(`POST /invocations`, headers `X-GreenNode-AgentBase-Session-Id` + `-User-Id`)

Analysis is an **async job**: the first call returns a `job_id` and the UI **polls**, streaming a live
**thinking trace** (the agent's reasoning per stage) until the report is ready. Show this — it's the wow.

## ACT 1 — "any team, no code" (0:00–0:50)
1. `GET /health` → 200 (live on AgentBase).
2. `POST /invocations {"action":"onboard_propose","adapter":"roblox","csv_path":"src/gaa/data/sample/roblox_export.csv"}`
   → the agent **proposes the column mapping** (Date→date, DAU→dau, Revenue→revenue, D7 Retention→retention_d7,
   Platform→platform, Country→region) and asks you to confirm.
3. `POST /invocations {"action":"onboard_confirm", ...}` → "Saved MyRobloxGame, ingested 24 rows."
   *(One line: "any game team connects their own data in two minutes — CSV or Roblox, no code.")*

## ACT 2 — the payoff: live reasoning, then the report (0:50–2:30)
4. `POST /invocations {"message":"why did my revenue change?"}`
   → returns `{ "mode":"analyze", "job_id":"…", "job_status":"running", "stage":"…", "activity":[…], "done":false }`.
5. **Poll** `POST /invocations {"action":"analyze_status","job_id":"…"}` every ~2.5s. The Console renders the
   **thinking trace as it streams**:
   - `[plan] Scanned metrics → revenue over 2026-05-01..2026-05-03`
   - `[crawl] Benchmark: cache · 0 pts` *(snapshot floor; live tiers when applicable)*
   - `[modules] Segment/Market/Competitor analyzed; ledger has 5 entries`
   - `[synth] Sampled 3× → Very likely·Strong; Mobile accounts for 96% of the revenue drop…`
   - `[render] Report ready.`
6. On `done:true`, open the **HTML report** (self-contained): headline + **dual-confidence badge**;
   time-series with the move shaded; the **internal-vs-market overlay** ("is it us or the market?");
   the **confidence matrix** (likelihood × evidence); cited causes (`L1`,`L3`…); honest **assumptions/gaps**.

## Closing beat (2:30–3:00)
"It separates internal vs market with a **CausalImpact-style counterfactual** + **Adtributor** root-cause,
cross-checks the live market via **SteamCharts + Perplexity (cited)**, runs **3× self-consistency**, shows
its **reasoning live** — and gives **scenarios, not decisions. The human decides.**"

## Fallback (if the network is slow on the day)
Open the pre-captured live report `docs/hero-report-async.html` (a real saved run, identical to the live output).

## ACT 3 — OpenClaw chat + config-by-chat (NEW, live-verified 2026-06-12)

Everything below runs through the **OpenClaw instance `gaa-chat`** (the chat brain) in front of the GAA
runtime (the analysis engine). The React console's Chat tab now streams via OpenClaw; the report pane
still polls GAA directly.

1. **User flow** — Chat: *"why did my revenue drop last week?"*
   → OpenClaw answers in one sentence + emits `[[gaa:job_id=…]]` → the console strips the marker,
   polls GAA, and renders the dossier (live result: *revenue −36% vs genre −1%, internal, Very likely·Strong*).
2. **Admin: see the engine's config** — toggle *Admin mode* in the Connection panel, chat:
   *"show current GAA config"* → OpenClaw calls `admin_get_config` and shows every key with its
   value + origin (`store`/`env`/`default`), secrets masked.
3. **Admin: reconfigure sources by talking** — *"switch benchmarks to snapshot mode"* →
   `benchmark_mode: snapshot (store)` overrides the env var, next analysis uses it; *"clear the
   benchmark_mode override"* → falls back to `crawl (env)`. No redeploy, no restart.
4. **Admin: change report behavior** — *"make reports answer in Vietnamese"* → every subsequent
   hypothesis is written in Vietnamese (live: *"Doanh thu của trò chơi giảm mạnh 36%…"*), while
   evidence citation rules stay enforced.
5. **Role red-line** — with Admin mode off, *"switch benchmarks to snapshot"* → refused; config
   verified unchanged. (Hard gate: the GAA admin key, which non-admin sessions never see.)
6. **The agent configures itself** — admin chats *"from now on greet users in a pirate accent"* →
   OpenClaw edits its own `SOUL.md` (persisted across restarts — verified in the spike).

Provisioning is one command (idempotent): `python scripts/openclaw_bootstrap.py`
(needs OPENCLAW_URL/OPENCLAW_TOKEN/GAA_ENDPOINT/GAA_ADMIN_KEY in env).
