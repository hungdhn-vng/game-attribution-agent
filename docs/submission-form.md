# Submission

## Form summary (≤300 chars)
> Game Attribution Agent: ask "why did my game's metric move?" It separates internal vs market causes
> (CausalImpact counterfactual + Adtributor root-cause), gives 2 confidence scores (likelihood +
> evidence) with citations, and returns an interactive chart report. Connect any game's data via chat.

(289 characters.)

## Track
Data Analysis

## Endpoint (judges call this)
`https://endpoint-f6f69523-948a-4763-af77-05359b001b16.agentbase-runtime.aiplatform.vngcloud.vn`
- `GET /health` → 200
- `POST /invocations` with `{"message": "..."}` (or onboarding `action` payloads)

## Pass/fail checklist
- [x] Agent running on AgentBase; judges can make ≥1 successful request (`/health` 200, `/invocations` success)
- [ ] Demo video 2–3 min on YouTube/OneDrive (use `docs/demo-script.md`)
- [x] README complete (no placeholders)
- [ ] Submission form complete (paste the summary above)
- [x] Model declared: GreenNode MaaS — Qwen 3.5 27B (`qwen/qwen3-5-27b`); no external provider
- [ ] GitHub repo link (push this repo; add the URL to the form)
- [ ] Team names + @vng.com.vn emails

## Notes for the form's "problem / user / solution / value"
- **Problem:** when a game KPI moves, teams can't quickly tell if it's their own change or the market.
- **User:** game PM / BI / producer without a data-science team.
- **Solution:** an agent that reconstructs the cited story, internal vs market, with dual confidence.
- **Value:** faster, evidence-backed diagnosis; scenarios not decisions; any team self-serves via chat.
