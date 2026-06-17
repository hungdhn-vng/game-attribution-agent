# Flexible Data Ingestion — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Branch:** feat/gaa-on-openclaw

## Problem

The agent only ingests **CSV**, and effectively expects a known layout. Today's path is
`_read_csv → Profiler.propose() → CSVAdapter.load()`:

- **Format:** only `pd.read_csv` — no Excel, no auto-delimiter, no JSON, no pasted-in-chat tables.
- **Shape:** `CSVAdapter` assumes a **wide** layout (date + dims as id_vars, metrics as value_vars to melt). Long-format, pivot/cross-tabs, or title rows above the header break it.
- **Vocabulary (the worst one):** `Profiler` maps columns only to a **fixed canonical metric list** (`dau, mau, revenue, arppu, retention_d1/d7/d30, sessions, playtime`) and 6 fixed dims, and is instructed to *"only include columns you are confident about."* Real columns outside that vocabulary — `ccu`, `ad_revenue`, `wishlists`, `game_mode`, `ab_group` — are **silently dropped**.
- **Errors:** failures surface as raw `str(exc)` stack-trace strings, useless to an end user.

Many different users feed the agent inconsistent data; it must absorb that variety itself.

### Prioritized pain points (from the user)
1. **File format variety** — Excel, other delimited, JSON/JSONL, pasted-in-chat tables.
2. **Unknown metrics/dims dropped** — passthrough instead of drop.
3. **Data shape/layout** — wide vs long, header detection, title rows.

Value/quality cleanup (number formats, dedup, granularity) is **lower priority** — only the cheapest wins are included.

## Approach (chosen: "Readers + declarative IngestionPlan + open schema")

Rejected alternatives:
- **A — expand the deterministic pipeline only:** hand-rolled shape heuristics get brittle on the long tail; doesn't use the model's strength at interpreting weird layouts.
- **B — LLM writes a pandas transform (code-gen adapter):** a weak MaaS model + arbitrary code execution = unpredictable and a real safety surface; hard to test deterministically.

**Chosen — C:** the LLM does **interpretation** (its strength); **reading and execution stay deterministic and testable** (code's strength). It is the natural generalization of what already exists:
`ColumnMapping → IngestionPlan`, `CSVAdapter → PlanAdapter`, `propose→confirm → confidence-gated confirm`.

## Interaction model

**Auto, confirm if unsure.** The agent auto-interprets format/shape/columns. When confident it
proceeds and reports what it did; it only stops to ask when genuinely ambiguous. This generalizes
today's propose→confirm into a confidence-gated flow.

## Architecture

```
raw input (file bytes  |  pasted text)
        │
   [1] READER LAYER          src/gaa/core/ingest/readers/
        │   sniff format → read → RawTable(df, read_spec, notes)
        ▼
   [2] PROFILER (LLM)         src/gaa/core/onboarding/profiler.py
        │   sample → IngestionPlan (orientation, mappings+passthrough, confidence)
        ▼
   [3] PLAN ADAPTER           src/gaa/core/adapters/plan_adapter.py
        │   execute plan deterministically → canonical long df → validate_canonical
        ▼
   open canonical schema      src/gaa/core/schema/canonical.py
```

Every existing seam is preserved: ingestion still flows through `gaa.server.actions.dispatch`,
the MCP tools (`onboard_propose` / `onboard_confirm`), the CLI, and the `/upload` front door.

## Components

### [1] Reader layer (new, deterministic) — `src/gaa/core/ingest/readers/`

One reader per format behind a `Reader` protocol, plus `detect.py` that picks a reader by
extension hint + content sniff (xlsx zip magic bytes, leading `{`/`[` for JSON, delimiter sniff,
else pasted-text).

- `csv_reader` — auto-delimiter (`sep=None`, `engine="python"` / `csv.Sniffer`) + encoding
  fallback (utf-8 → latin-1). Keeps today's NA-safe rules (`keep_default_na=False, na_values=[""]`)
  so `"NA"` (North America) survives.
- `excel_reader` — openpyxl; **finds the header row** (skips title rows above it); handles
  multi-sheet (picks the most tabular sheet, or surfaces the sheet choice via `notes`).
- `json_reader` — JSON arrays via `json_normalize`; JSONL line-by-line.
- `paste_reader` — parses a markdown / TSV / whitespace table pasted directly into chat (no file).

Each returns a **`RawTable`** = `{df, read_spec, notes}`.
`read_spec` = `{format, delimiter, encoding, sheet, header_row}` — recorded so the **confirm**
step re-reads **identically** to the **propose** step (determinism between the two calls).

### [2] IngestionPlan + upgraded Profiler

`IngestionPlan` (Pydantic, `src/gaa/core/schema/ingest_plan.py`) — a **declarative** description
the LLM produces; never code:

```python
class ReadSpec(BaseModel):
    format: Literal["csv", "excel", "json", "jsonl", "paste"]
    delimiter: str | None = None
    encoding: str | None = None
    sheet: str | None = None
    header_row: int = 0

class IngestionPlan(BaseModel):
    read_spec: ReadSpec
    orientation: Literal["wide", "long"]
    date_col: str
    # WIDE: metrics live in columns →  source_col -> final metric name
    metric_cols: dict[str, str] = {}
    # LONG: metric names + values live in two columns
    long_metric_col: str | None = None
    long_value_col:  str | None = None
    dim_cols: dict[str, str] = {}        # source_col -> dim name (canonical OR preserved)
    confidence: float                    # 0.0–1.0 overall
    notes: list[str] = []                # plain-language decisions/uncertainties
```

Profiler changes (`profiler.py`):
- New system prompt: map to a canonical name **when one fits; otherwise keep the column with a
  normalized name** (passthrough, not drop). Detect `orientation`. Emit `confidence` + `notes`.
- `propose(raw_table) -> IngestionPlan`.
- `summary(plan, preview_df) -> str` — plain-language "Here's how I read your file…" with a small
  preview, phrased by confidence.

**Passthrough is the fix for dropped columns.** A recognized synonym maps to its canonical name
(`DAU → dau`); an unrecognized column is **kept verbatim** (`ccu`, `wishlists` stay as-is) and
`notes` says "kept ccu, wishlists as custom metrics." Verbatim-by-default avoids surprise renames.

### [3] PlanAdapter (replaces CSVAdapter) — `src/gaa/core/adapters/plan_adapter.py`

One deterministic executor: `RawTable + IngestionPlan → canonical long DataFrame`.

- **Wide:** melt `metric_cols` (like today's `CSVAdapter`) but **do not drop** passthrough metrics;
  rename `dim_cols`, keeping passthrough dims.
- **Long:** rename `long_metric_col → metric`, `long_value_col → value`, `date_col → date`, dims →
  dim names; values are already per-row.
- **Value coercion (minimal quality win):** strip thousands separators / currency symbols /
  trailing `%` when casting `value` to float (`"1,234"`, `"$500"`, `"45%"`). Anything still
  non-numeric → `bad_values`.
- Calls `validate_canonical` (open).

`CSVAdapter` is retired. `RobloxAdapter` is unchanged.

#### Worked example (wide, multi-metric — the common case)

Input:
```
date,        platform, dau,  ccu, revenue, wishlists
2026-01-01,  ios,      1000, 200, 500,     30
2026-01-01,  android,  1500, 280, 600,     45
```

Plan: `orientation="wide"`, `date_col="date"`, `dim_cols={platform: platform}`,
`metric_cols={dau: dau, ccu: ccu, revenue: revenue, wishlists: wishlists}`.

Output (each metric column melted into its own rows; `ccu`/`wishlists` preserved instead of
dropped):
```
date        metric     value  platform
2026-01-01  dau        1000   ios
2026-01-01  ccu         200   ios
2026-01-01  revenue     500   ios
2026-01-01  wishlists    30   ios
2026-01-01  dau        1500   android
...
```

### Open canonical schema — `src/gaa/core/schema/canonical.py`

- `REQUIRED_COLUMNS` (`date, metric, value`) unchanged.
- `CANONICAL_DIMS` stays as the **known** dims (benchmark logic relies on them, e.g. region).
- `validate_canonical` now **keeps extra dim columns** instead of restricting to `ALL_COLUMNS`.
- New helper `dim_columns(df)` → all dim columns present (canonical + extra).
- Metrics were already open (any string).

### Downstream tweak (surgical)

- `segment.py` — default dims from `dim_columns(ctx.metrics)` instead of the fixed `DIMS`.
- `exploration.py` — iterate `dim_columns(ctx.metrics)` instead of `CANONICAL_DIMS`.

Result: a custom dim like `game_mode` becomes drillable and explorable. `market_benchmark.py`
already degrades gracefully ("no benchmark available") for metrics it doesn't recognize — no change.

### Onboarding tools rewire

- `onboard_propose` — accepts a generic source: `filename` + `content_b64` (any format) **or**
  pasted `text`; keeps `csv` / `csv_b64` as compat aliases. Returns
  `{plan, summary, preview, confidence, auto_ok}` where `auto_ok = confidence >= THRESHOLD`
  (~0.8, config-tunable).
- `onboard_confirm` — takes the (possibly user-edited) `plan`, re-reads the full file via
  `read_spec`, runs `PlanAdapter`, saves profile + metrics. `GameProfile` stores the full plan
  (replacing/extending the bare `mapping`).
- `/upload` server endpoint — widened to accept non-CSV bytes + `filename` (today it assumes CSV).

### Confidence gate (in the SOUL onboarding playbook)

- `auto_ok == true` → call `onboard_confirm` immediately, then report what was read
  (format, sheet, layout, mapped vs kept-as-custom columns, row count).
- `auto_ok == false` or any ambiguity in `notes` → show the summary + preview and **ask** before
  confirming.

## Data flow

```
A) File upload                          B) Pasted table in chat
   user drops file.xlsx                    user pastes a TSV/markdown table
        │                                        │
   /upload (filename + bytes)            agent calls onboard_propose(text=…)
        │                                        │
        └──────────────┬─────────────────────────┘
                       ▼
        detect.py  →  pick reader  →  RawTable(df, read_spec, notes)
                       ▼
        Profiler.propose(sample)  →  IngestionPlan(+confidence)
                       ▼
        return { plan, summary, preview, confidence, auto_ok }
                       ▼
        ┌─────── auto_ok? ───────┐
        │ true                   │ false
        ▼                        ▼
   onboard_confirm          agent shows summary+preview, asks;
        │                   user confirms / edits the plan
        │                        │
        └────────────┬───────────┘
                     ▼
   re-read full file via read_spec → PlanAdapter.load(raw, plan)
                     ▼
   validate_canonical (open) → metrics.save + profiles.save
                     ▼
   "Ingested N rows, M metrics. Analyzing…"
```

## Error handling

Every stage returns a **structured, user-facing error** (`{status:"error", error:<code>, detail,
hint}`) instead of raw `str(exc)`:

| Stage | Failure | Response |
|---|---|---|
| detect | unknown/empty/corrupt input | `unreadable_file` + hint listing supported formats |
| reader | xlsx has no tabular sheet / can't find header | `no_table_found` + which sheets were seen |
| profiler | LLM returns an invalid plan | retry **once**, then `cannot_interpret` + the raw column list so the agent can ask the user |
| adapter | named col missing / melt fails | `plan_mismatch` naming the offending column → agent re-proposes or asks |
| validate | non-numeric values after coercion / unparseable dates | `bad_values` naming the metric/column + an example offending cell |

**Low confidence is not an error** — it routes to the confirm path. Principle: the agent always
gets something it can act on or relay, never a stack trace.

## Testing (TDD; keep the full suite green — 415+ tests)

- **Readers** — fixtures: semicolon CSV, latin-1 encoding, `.xlsx` with title rows + a junk second
  sheet, JSON array, JSONL, pasted markdown, pasted TSV → assert `RawTable.df` + `read_spec`.
- **detect.py** — every fixture routes to the correct reader; corrupt/empty → `unreadable_file`.
- **IngestionPlan** — pydantic validation; passthrough fields; wide vs long required-field rules.
- **PlanAdapter** — wide melt preserves passthrough metric (`ccu`) **and** passthrough dim
  (`game_mode`); long passthrough; value coercion; → `validate_canonical`.
- **Open canonical** — extra dim survives; `dim_columns()` returns canonical + extra.
- **Profiler** — stub `LLM` returns a plan: orientation/passthrough/confidence parsed; invalid
  plan → retry-once → `cannot_interpret`.
- **Downstream regression** — `segment.py` / `exploration.py` pick up a custom dim (`game_mode`).
- **onboard_propose / confirm** — end-to-end with a fake LLM per format; `auto_ok` thresholding
  (high → confirm path, low → ask path).

## Scope

**In scope:** Excel, auto-delimited/other-delimited, JSON/JSONL, pasted-in-chat; passthrough open
schema; confidence-gated confirm; structured errors; minimal value coercion.

**Non-goals (this iteration):**
- Google Sheets / live-URL fetch (pasted text covers the "no file" case).
- Multi-file / folder ingestion (one table per onboard).
- Heavy cleaning — dedup, granularity reconciliation (daily↔weekly), fuzzy date-locale parsing
  beyond pandas defaults.
- `RobloxAdapter` re-expressed as a plan (stays unchanged).
