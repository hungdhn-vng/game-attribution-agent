---
name: gaa
description: Drive the Game Attribution Agent (GAA) — answer "is it us or the market?" for a game's metrics by running the `gaa` CLI in this workspace. Analysis, follow-up drilldowns, onboarding, and (admin only) configuration + tools.
---

# Game Attribution Agent (GAA)

The `gaa` CLI lives in this workspace (installed from the repo under `~/.openclaw/workspace/gaa`).
It outputs **compact JSON on stdout** — read it, don't guess. The exec shell is POSIX `sh`
(use `.` not `source`).

## Just run `gaa`
`gaa` is installed on PATH and is self-contained — it loads its own workspace config and
credentials, so run it directly from any directory, e.g.:

    gaa analyze "<the user's question, verbatim>" --budget 2

(No `cd` or sourcing needed for `gaa` commands — a wrapper handles that.)

## Run things yourself, in this turn
Run `gaa` with your exec tool IN THE SAME TURN and reply immediately. NEVER spawn subagents or
background tasks. Long commands get backgrounded with a random process name (e.g. "keen-crustacean")
— that name is **NOT** a run id; never treat it as one. Always use the budgeted forms below.

## Decision guide — pick the smallest command that fits
1. **A fresh question about a game's metrics** ("why did revenue drop?", "what's going on with my game?")
   → start an analysis:
   `gaa analyze "<the user's question, verbatim>" --budget 2`
   It returns fast with a `run_id`, `status`, `stage`. See references/analysis.md.
2. **A follow-up about an existing run** ("which region?", "re-check vs the market", "answer my new question")
   → a drilldown against that run, then re-synthesize: `gaa segments --run <id> --dimension region`,
   then `gaa synth --run <id> "<follow-up>"` and `gaa report --run <id>`. See references/drilldowns.md.
3. **Nothing built-in fits** (a bespoke calculation) → write a short scratch script using `gaa.lab`
   and run it. See references/adhoc.md.
4. **You're unsure which runs exist** → `gaa jobs`. NEVER invent or shorten a run id — re-discover it.
5. **Connect data / switch games** → references/onboarding.md.
6. **Configuration, health, tools (ADMIN ONLY)** → references/admin.md.

## The report marker (for the web UI)
When you start an analysis for a user, reply with ONE short sentence and end with this exact line:

    [[gaa:run_id=<run_id>]]

Copy `<run_id>` verbatim from the `gaa analyze` JSON output. If you did not actually run the command,
or it errored, do NOT emit a marker — report the problem instead. The web UI detects the marker,
polls the run itself, and renders the dossier — so you never paste the full report into chat.

## Reading run status
`gaa status <run_id>` (read-only) and `gaa step <run_id>` (advance one slice) report
`{status, stage, done, activity, ledger_count, report_path (once done)}`. The UI drives stepping;
in pure chat you may `gaa step` a few times until `done`, then relay `gaa status`'s `summary_path`.
