# Demo script (2–3 min video)

Endpoint: `https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn`
(`POST /invocations`, headers `X-GreenNode-AgentBase-Session-Id` + `-User-Id`)

## ACT 1 — "any team, no code" (0:00–1:00)
1. Show `GET /health` → 200 (it's live on AgentBase).
2. `POST /invocations {"action":"onboard_propose","adapter":"roblox","csv_path":"src/gaa/data/sample/roblox_export.csv"}`
   → the agent **proposes the column mapping** (Date→date, DAU→dau, Revenue→revenue, D7 Retention→retention_d7,
   Platform→platform, Country→region) and asks you to confirm.
3. `POST /invocations {"action":"onboard_confirm", ...}` → "Saved MyRobloxGame, ingested 24 rows."
   *(One line: "any game team connects their own data in two minutes — CSV or Roblox, no code.")*

## ACT 2 — the payoff (1:00–2:30)
4. `POST /invocations {"message":"what is going on with my game?"}`
   → the agent **discovers the notable movement** (scan mode) and returns the report.
5. Open the returned **HTML** (`response.html`, self-contained): headline + **dual-confidence badge**;
   the time-series with the move highlighted; the **internal-vs-market overlay** ("is it us or the market?");
   the **confidence matrix** (likelihood × evidence); cited causes (`L1`,`L2`…); honest **assumptions/gaps**.
6. Read the one-line markdown summary aloud.

## Closing beat (2:30–3:00)
"Two confidence axes, every claim cited, internal vs market separated by a CausalImpact-style
counterfactual and Adtributor root-cause — and it gives **scenarios, not decisions. The human decides.**"

## Fallback (if the network is slow on the day)
Open the pre-captured hero report `docs/hero-report.html` (a real saved run) — identical to the live output.
