# Submission

## Form summary (≤300 chars)
> Game Attribution Agent: ask "why did my game's metric move?" It separates internal vs market causes
> (CausalImpact counterfactual + Adtributor root-cause), cross-checks live market data (SteamCharts +
> Perplexity, cited), gives 2 confidence scores with citations, and streams its reasoning live. Connect
> any game's data via chat.

(297 characters.)

## Track
Data Analysis

## Endpoint (judges call this)
`https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn`
- `GET /health` → 200
- **Analyze is an async job:** `POST /invocations {"message":"…"}` → `{job_id, job_status, stage, activity[], done}`;
  poll `POST /invocations {"action":"analyze_status","job_id":"…"}` until `done:true` → `{hypothesis, markdown_summary, html}`.
  (Each request stays <50s; the job resumes across polls. Onboarding: `{"action":"onboard_propose|onboard_confirm", …}`.)

## Pass/fail checklist
- [x] Agent running on AgentBase; judges can make ≥1 successful request (`/health` 200; `/invocations` async analyze verified live — start `done` in 16s, poll 0.5s)
- [ ] Demo video 2–3 min on YouTube/OneDrive (use `docs/demo-script.md`)
- [x] README complete (no placeholders)
- [ ] Submission form complete (paste the summary above)
- [x] Model declared: GreenNode MaaS — Qwen 3.5 27B (`qwen/qwen3-5-27b`); **Perplexity `sonar`** declared as external (web/qualitative tier, key-gated)
- [ ] GitHub repo link (push this repo; add the URL to the form)
- [ ] Team names + @vng.com.vn emails

## Notes for the form's "problem / user / solution / value"
- **Problem:** when a game KPI moves, teams can't quickly tell if it's their own change or the market.
- **User:** game PM / BI / producer without a data-science team.
- **Solution:** an agent that reconstructs the cited story — internal vs market — with dual confidence, a live
  market cross-check (SteamCharts + Perplexity), and a visible reasoning trace.
- **Value:** faster, evidence-backed, trustworthy diagnosis; scenarios not decisions; any team self-serves via chat.
