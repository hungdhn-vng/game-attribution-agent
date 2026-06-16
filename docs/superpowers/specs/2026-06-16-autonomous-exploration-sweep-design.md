# Autonomous Exploration Sweep — Design

**Date:** 2026-06-16
**Status:** Approved (brainstorming), pending implementation plan
**Branch context:** `feat/gaa-on-openclaw` (GAA on self-hosted OpenClaw)

## Motivation

GAA today answers *the question asked*. The `analyze` pipeline parses one metric +
direction from the query and runs targeted modules (`SegmentDecomposition`,
`AnomalyDetection`, `MarketBenchmark`, `CompetitorSignals`, `MigrationPattern`)
that decompose **that** metric along its best single dimension. Nothing
systematically mines the data for high-impact findings the user did **not** ask
about. The goal of this slice is *deeper, non-obvious insight*: surface the
"you didn't ask, but this matters" findings, grounded and cited the same way
every other finding is.

This was chosen over alternatives after research (see
`/tmp` deep-research output, 2026-06-16) showed that for GAA's **open-weights
MaaS model**, agent-driven free-form code execution (the LLM writing analysis
code live) is the highest-risk path — small/open models are weakest at exactly
the planning/code-generation that approach demands, and it reintroduces tool-token
and tool-poisoning/RCE surface. A **deterministic engine-driven sweep** that feeds
the existing evidence ledger keeps the floor high: reliable computation, grounded
findings, the LLM only narrating (its strength), zero new agent-loop tokens, zero
new attack surface.

This is the **first of three slices** toward "deep insight":
1. **Autonomous exploration** (this spec) — *generate* non-obvious findings.
2. Prescriptive + forecast — *act on* findings (recommendations, what-if). Later.
3. Sharper synthesis — *communicate* findings (lead with what matters). Later.
Each is its own spec → plan → build cycle. Exploration is first because it is the
source of the depth the other two package.

## Goals

- A new deterministic analysis stage that mines **all** metrics × dimensions for
  high-impact, novel findings and writes the top few into the evidence ledger.
- Findings are grounded (claim/value/source/strength) and cited exactly like
  existing module output, so they flow into synth and the dossier with no
  special-casing.
- Reliable on a weak model: no LLM-authored analysis code; the LLM only narrates.
- No new tools on the OpenClaw chat loop; no change to its token budget or attack
  surface.

## Non-goals (explicitly deferred)

- Dedicated "lead with the 2–3 that matter" dossier presentation → **Sharper
  synthesis** slice. (Exploration findings already render in the dossier's
  evidence section in this slice.)
- Recommendations / forecasts / what-if scenarios → **Prescriptive** slice.
  (Synth's current SYSTEM prompt deliberately says "Present scenarios, never
  prescribe decisions" — unchanged here.)
- Agent-callable interactive drill-down tools (the "bounded toolkit" / approach C)
  → possible fast-follow after this proves out.
- Cohort/retention-curve probe and a dedicated un-asked change-point probe →
  fast-follow (kept out to keep this slice tight).

## Architecture

### Component

`core/modules/exploration.py` → `ExplorationSweep`, implementing the existing
`AnalysisModule` protocol (`name: str`; `run(ctx: AnalysisContext, ledger:
EvidenceLedger) -> None`; **never raises** on missing data — records a derived
'data gap' entry instead, per the protocol contract in `core/modules/base.py`).

### Integration point

`runs/pipeline.py::_stage_modules`, appended **after** the existing modules:

```python
SegmentDecomposition().run(ctx, ledger)
MarketBenchmark(self.benchmark).run(ctx, ledger)
CompetitorSignals(self.signals).run(ctx, ledger)
MigrationPattern().run(ctx, ledger)
ExplorationSweep().run(ctx, ledger)          # NEW — runs last
```

Running last lets it read `ledger.all()` for the novelty gate (avoid
re-reporting what targeted modules already surfaced). The stage then persists
`state["ledger"]` and emits a `job.add_activity("explore", …)` line for live
narration, consistent with the existing `add_activity` calls.

### Data model — no schema change

Findings are written via `ledger.add(...)` with:
- `source_type="derived"` (the allowed `Literal["internal","external","derived"]`
  is unchanged),
- `module="exploration"` (the distinguishing tag),
- `source` string naming the probe + computation (e.g.
  `"internal:retention_d7 by region×version (interaction)"`),
- `strength` mapped from effect size (see Scoring),
- `timeframe` set to the comparison window when applicable.

`AnalysisContext` already carries everything needed: `profile`, `metrics`
(canonical long-format DataFrame with `metric`, `date`, `value`, and dimension
columns `version/region/platform/cohort/device/source`), `metric`, `start`,
`end`, `direction`, `extras`.

## The probe battery (v1)

All probes are deterministic Python reusing existing analytics
(`adtributor_dimension`, change-point, `aggregate.is_aggregate_label`). Each probe
yields zero or more **candidate findings**, each with an `effect_size` and a
`surprise` measure used for ranking.

### P1 — Surprise scan across all metrics × dimensions
Generalizes `SegmentDecomposition` from "queried metric, best dim" to **every
metric × every dimension**. For each (metric, dim) with usable data, drop
pre-aggregated rows (`is_aggregate_label`), build start/end group sums, run
`adtributor_dimension(forecast, actual)`, and collect the top surprising elements.
Surfaces movers in metrics the user didn't ask about.
*Effect:* element explanatory power (`ep`). *Surprise:* Adtributor `surprise`.

### P2 — 2-way interaction scan (marquee)
For pairs of dimensions (bounded — see Performance), find the **cell** whose joint
movement exceeds the sum of its two marginal movements (an interaction effect):
the non-obvious "the drop concentrates in `region=SEA × version=v2.3`
specifically." Computed from start/end crosstabs; interaction magnitude =
|joint Δ − (marginal_A Δ + marginal_B Δ)| normalized.
*Effect:* normalized interaction magnitude. *Surprise:* interaction / marginal
ratio.

### P3 — Cross-metric lead-lag
Across metric time series, compute correlation and a simple lead-lag (shift in
{−7..+7} days maximizing |correlation|), reusing change-point to anchor moves.
Surfaces "D7 retention fell a week **before** DAU."
*Effect:* |correlation| at best lag. *Surprise:* lead time (a leading indicator is
more surprising/actionable than a coincident one).

### P4 — Data-quality flags (cheap)
Scan series for gaps, zero/negative spikes, and abrupt scale shifts. Emitted as
**low-strength** caveats; these also strengthen synth's `assumptions_and_gaps`
(a reliability win, not just an insight win).
*Effect/Surprise:* fixed low; always low strength.

## Scoring, novelty gate, cap

- **Score** per candidate = `effect_size × surprise` (each probe normalizes its
  two measures to [0,1] so scores are comparable across probes).
- **Novelty gate:** drop a candidate if a targeted-module ledger entry of
  equal-or-higher strength already covers the same (metric, dimension, element).
  Matching is structural (metric + dim + element key), not string-fuzzy.
- **Cap:** keep the **top-N (default 4)** candidates across all probes after the
  novelty gate. Report the dropped count in the `add_activity` line — **no silent
  truncation**.
- **Strength mapping** mirrors `segment.py`: high if `|effect| ≥ 0.5`, med if
  `≥ 0.2`, else low. P4 is always low.

## Synth awareness (the one allowed synth touch)

Minimal, to make exploration findings *visible* to the model without building the
later presentation layer:
- `synth/synthesizer.py::_ledger_brief` includes the `module` field in each line
  so the LLM can see `[exploration]`-tagged evidence.
- One line added to `SYSTEM`: evidence whose module is `exploration` are
  proactive findings the user did not explicitly ask about — surface notable ones.

No schema change to `AttributionHypothesis`; no new dossier section in this slice.
Findings render in the existing evidence ledger view of the dossier.

## Config & performance

- Enable/disable + `top_n` exposed through the existing `config_get/config_set`
  seam (default: enabled, `top_n=4`).
- **P2 is the cost driver** (O(dims²) × cells). Bound it: scan only the **top-K
  dimensions by marginal surprise** (default K=3) and only the queried metric +
  the top-2 movers from P1. An overall combo cap guards the stage; if exceeded,
  remaining probe work is skipped and the skip is noted (respects the pipeline's
  mid-pipeline resume/deadline model — see `_stage_modules` comments).

## Error handling

Per the `AnalysisModule` contract: each probe is individually wrapped; on missing
columns or any exception, the probe is skipped and at most one low-strength
'data gap' entry is recorded. `ExplorationSweep.run` **never raises** — a probe
failure must not fail the run.

## Testing (TDD)

- **Per-probe unit tests with planted signals** in synthetic DataFrames:
  - P1: a non-queried metric with an injected dimension shift → asserted surfaced.
  - P2: data where `region=SEA × version=v2.3` holds the interaction → asserted
    that cell is found and outranks the marginals.
  - P3: two series where one leads the other by N days → asserted lead-lag found.
  - P4: injected gap / negative spike → asserted flagged low-strength.
- **Novelty/dedup:** a finding already reported by `SegmentDecomposition` is NOT
  re-added by exploration.
- **Ranking/cap/strength:** top-N respected; ordering by score; strength mapping
  correct; dropped count reported.
- **Robustness (never-raise):** empty df, missing dims, single date, all-NaN dim
  → no exception, graceful skip.
- **Integration:** run through `_stage_modules` with `ExplorationSweep`
  registered → ledger gains `module=exploration` entries → synth runs and cites
  them.

## File-level change list

- **New:** `src/gaa/core/modules/exploration.py` (`ExplorationSweep` + probes).
- **Edit:** `src/gaa/runs/pipeline.py::_stage_modules` (register module last;
  add activity line).
- **Edit:** `src/gaa/core/synth/synthesizer.py` (`_ledger_brief` shows `module`;
  one SYSTEM line).
- **Edit:** config defaults for `exploration.enabled` / `exploration.top_n`
  (wherever runtime config defaults live; reuse `config_get/set`).
- **New tests:** `tests/` unit + integration per the Testing section.
- **Possible reuse:** the same probes may be exposed via
  `cli/commands/primitives.py` for ad-hoc/ops use (optional, not required).

## Risks & open questions

- **Value depends on data richness.** Interaction/lead-lag probes need multiple
  dimensions and metrics over enough dates; on thin data they degrade to P1 +
  data-quality. Acceptable (graceful), but demo data should exercise them.
- **Ledger/synth context budget.** top-N=4 keeps added evidence small; if synth
  context pressure shows up, lower N or summarize. (Ties to the token discipline
  the research validated.)
- **Open:** exact normalization for P2/P3 effect/surprise so scores are
  comparable across probes — to be finalized during implementation with the
  planted-signal tests as ground truth.
- **Open:** whether to also surface exploration findings via a CLI primitive for
  ops/debugging (low cost; decide in the plan).
