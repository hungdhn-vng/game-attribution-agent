# Market & Social Research — Design Spec

- **Date:** 2026-06-14
- **Status:** Approved (brainstorming) → ready for implementation plan
- **Scope:** Upgrade the GAA `market` and `signals` analysis legs from thin/dead placeholders into dynamic, cited, quantitative research that feeds attribution — including the question *"are my users migrating to an influencer-boosted competitor?"*

---

## 1. Context & problem

The Game Attribution Agent (GAA) diagnoses *why* a game metric moved by triangulating three kinds of cause: **internal** (`segment`), **market-wide** (`market`), and **external-specific** (`signals`/`competitor`). Live testing (2026-06-14) showed:

- The `market` leg emits only a one-sentence `trend up/down/flat` verdict and, for the test game, returned *"no genre benchmark available"* then a vague qualitative note. With the profile mis-set to `platform="Custom"`, the web crawl even researched **retail e-commerce** instead of games.
- The `signals`/`competitor` leg is **dead**: `DynamicSignals` has no configured source, so `CompetitorSignals` always records *"no external competitor/event signals found in window"*.
- The crawl machinery itself works (verified live: Perplexity returns cited, relevant results when given a real genre/platform; e.g. roblox/simulator and Roblox D1-retention benchmarks).

Deep research into professional live-game analytics practice (2023–2026) confirmed the standard loop is exactly anomaly → segmentation → contribution decomposition → causal counterfactual → **benchmark to separate market-wide from game-specific**, and that benchmarks must be **pulled dynamically, cited, and treated as genre/platform-relative** (values drift; many online numbers are wrong). It also confirmed external demand shocks (influencer coverage, social virality, competitor launches) are a first-class attribution cause that the dead `signals` leg should be capturing.

## 2. Goals

1. **Quantitative, cited benchmark** for the analyzed metric, genre- and platform-relative, compared to the game's actual value (market-wide vs game-specific).
2. **Influencer / social-trend signals** — game-specific *and* genre-wide — as external-cause evidence in the ledger.
3. **Explicitly support the migration question:** when a *game-specific* decline coincides with a *competitor's influencer-driven rise* near the change-point, surface a "likely player migration to {competitor}" hypothesis with honest confidence and caveats.
4. Everything **dynamic** (no hard-coded benchmark numbers), **cited**, **graceful** (never crashes a job), and **admin-configurable**.

## 3. Non-goals (YAGNI)

- Dedicated social-platform APIs (YouTube/TikTok/Twitch/Reddit) — Perplexity web research only.
- Tiered structured benchmark sources (Roblox dashboard scraping, GameAnalytics ingestion) — future.
- Per-run multi-agent deep-research loop — too token/latency-heavy for the per-analysis budget.
- Hard-coded per-genre benchmark tables — research says pull dynamically.
- **Proof** of user-level migration — fundamentally unobservable from first-party data (see §7); we produce a *hypothesis*, not a fact.

## 4. Architecture overview

Two research legs share one helper and feed the two existing modules; a small detector reads the resulting ledger to assemble the migration hypothesis.

```
                      ┌─ research_json(answer_fn, prompt) → parsed | None   (shared, graceful, cited)
                      │
 Leg 1 (benchmark) ───┤  WebSearchBenchmarkProvider.metric_benchmark()
                      │      → BenchmarkStore.put/get_benchmark (kind="benchmark", per metric, 7d TTL)
                      │      → MarketBenchmark.run(): compare game value vs benchmark range  ──┐
                      │                                                                        │
 Leg 2 (social) ──────┤  SocialSignalProvider.events()  (game + genre, dated, scope-tagged)   ├─► EvidenceLedger
                      │      → DynamicSignals.events() wiring                                   │
                      │      → CompetitorSignals.run(): per-signal external entries  ──────────┘
                      │
 Migration ───────────┘  MigrationPattern.run(): reads ledger → derived "likely migration" entry
```

- **Leg 1** runs in the pipeline **crawl** stage (via `BenchmarkRefresher`, under the crawl deadline budget) and is read in the **modules** stage by `MarketBenchmark`.
- **Leg 2** runs in the **modules** stage (via `CompetitorSignals` → `signals.events()`), bounded by the HTTP timeout + cache.
- **MigrationPattern** runs in the **modules** stage *after* `market` and `competitor`, so both their ledger entries exist.

## 5. Components

Each unit is single-purpose, has a narrow interface, and is testable in isolation with a fake `answer_fn` (no network in tests).

### 5.1 `gaa/core/crawl/research.py::research_json` (new, shared)
- **Does:** `research_json(answer_fn, prompt) -> dict | list | None`. Calls `answer_fn(prompt)` (Perplexity), runs `_extract_json` on the content, attaches the returned `citations`, returns the parsed object. Returns `None` on any exception or parse failure.
- **Deps:** `gaa.core.llm.client._extract_json`. `answer_fn` injected (prod: `lambda p: perplexity_answer(p, settings)`).
- **Why:** one place to own the "prompt → cited JSON → graceful degrade" behavior both legs need.

### 5.2 `WebSearchBenchmarkProvider.metric_benchmark` (extend `sources/providers/web.py`)
- **Does:** `metric_benchmark(metric, genre, platform, start, end) -> dict | None`. Builds a prompt asking for the benchmark **range** for the human-readable metric (`retention_d1`→"Day 1 retention", `retention_d7`→"Day 7 retention", `dau`→"daily active users", `arppu`→"ARPPU", `revenue`→"revenue") in `{genre}` games on `{platform}`, demanding strict JSON `{low, high, median?, unit, source, confidence}` plus sources. Uses `research_json`. **Normalizes `unit` to the metric's native scale** (percent→fraction for rate metrics). Returns the structured dict + `citations`, or `None`.
- **Deps:** `research_json`, a `metric→human-readable` map, a `RATE_METRICS` check (reuse `analytics/aggregate.RATE_METRICS`).

### 5.3 `BenchmarkStore.put_benchmark` / `get_benchmark` (extend `store/benchmark_store.py`)
- **Does:** persist/read a benchmark under `kind="benchmark"`, keyed within the payload by metric: `get_benchmark(platform, genre, metric)`, `put_benchmark(platform, genre, metric, payload)`. Reuses the existing `fetched_at` column and `is_fresh(platform, genre, kind, ttl)` (TTL = 7 days).
- **Deps:** existing sqlite schema (`platform, genre, kind, payload, fetched_at`). Payload stores `{metric: {...}}` so multiple metrics coexist under one `(platform, genre, "benchmark")` row.

### 5.4 `BenchmarkRefresher.refresh(..., metric=None)` (extend `crawl/refresher.py`)
- **Does:** after the existing quant/qual tiers, if `web_provider` and `metric` are present and a cached fresh benchmark is absent, call `web_provider.metric_benchmark(metric, genre, platform, start, end)` and `store.put_benchmark(...)`. Additive `metric` kwarg (default `None` → existing behavior, existing callers/tests unaffected).
- **Deps:** `web_provider` (the benchmark provider), `store`.

### 5.5 `DynamicRefresher.refresh(..., metric=None)` (extend `sources/dynamic.py`)
- **Does:** thread `metric` through to `BenchmarkRefresher.refresh`. The pipeline `_stage_crawl` passes `state["metric"]`.

### 5.6 `CrawlingBenchmarkSource.metric_benchmark` (extend `sources/crawling_benchmark.py`)
- **Does:** `metric_benchmark(metric, genre) -> dict | None` → `store.get_benchmark(self._platform, genre, metric)`. (Read side, used by `MarketBenchmark`.)

### 5.7 `MarketBenchmark.run` (extend `modules/market_benchmark.py`)
- **Does:** after the existing trend/CausalImpact/qualitative logic, if `getattr(source, "metric_benchmark", ...)(ctx.metric, genre)` returns a benchmark, compute the game value `g = metric_series(ctx.metrics, ctx.metric).iloc[-1]` and emit a cited comparison entry:
  - `g < low` → "below benchmark → underperforming the {genre} market"
  - `g > high` → "above benchmark → outperforming"
  - else → "in line with the {genre} market"
  - `value` includes the numbers (`g` vs `low–high`); `source` = benchmark `source`/citation; `source_type="external"`; `strength` = `med` (estimate), downgraded to `low` if `confidence=="low"` or no citations; `timeframe` = window.
- **Guarded** in try/except → degrade to existing paths; never raises. (Also closes the Bug-6 unguarded-causal gap for this code.)
- **Deps:** `analytics/aggregate.metric_series` (de-duped `Total`, not a sum).

### 5.8 `SocialSignalProvider.events` (new, `sources/social_signals.py`)
- **Interface:** `events(game, genre, start, end) -> list[dict]` — matches the existing `SignalsSource` protocol exactly (no `platform` param). `game` is the **human game title** (see §5.12), supplied by `CompetitorSignals`. Platform is an optional construction-time hint woven into the prompt.
- **Does:** One `research_json` call asking for **dated** influencer/social events in the window, covering **both**:
  - *game-specific:* did an influencer feature **this** game? a viral TikTok/Reddit/short moment?
  - *genre-wide:* is the genre trending socially / with influencers?
  - **competitor-substitution (migration sharpening):** *which competing games gained players or attention in this window, and was it influencer-driven — name the game, the influencer/channel, and the date.*
  
  Returns a JSON list; each item normalized to the event shape `CompetitorSignals` consumes plus extras: `{date, kind: "influencer"|"social_trend"|"competitor_event", scope: "game"|"genre", entity, reach, url, summary, sentiment, title}`. Window-filtered by `date`. Returns `[]` on any failure.
- **Deps:** `research_json`. Implements the `SignalsSource` `events(...)` interface.

### 5.9 `DynamicSignals.events` wiring (extend `sources/dynamic.py`)
- **Does:** when `perplexity_api_key` is present and signal-crawl mode is on (reuse `benchmark_mode=="crawl"` or a new `signals_mode` config key), build a `SocialSignalProvider(answer_fn=lambda p: perplexity_answer(p, settings), platform=<cfg/profile platform>)` and return its `events(...)`. Else fall back to the existing `WebSignalsSource` (URL template) or `FixtureSignalsSource([])`. Mirrors `DynamicRefresher._build`.

### 5.10 `CompetitorSignals.run` enrichment (extend `modules/competitor_signals.py`)
- **Does:** keep the existing graceful/empty paths. For each event, use `scope`/`entity`/`reach` in the claim:
  - `scope="game"` → "external: {entity} {kind} on {date} (reach {reach}) — may explain the {metric} move"
  - `scope="genre"` → "genre social trend: {summary}"
  - Refine strength: a **game-scoped, high-reach influencer/competitor_event near the change-point** → `high`/`med`; genre-scoped → `low`/`med`. Add `"influencer"` to `_STRENGTH_BY_KIND`.
  - Passes the **game title** (`ctx.profile.title or ctx.profile.name`, see §5.12) as the `game` arg to `events()`, so a game-specific search uses the real title rather than the CSV-derived profile key.
- Existing entries (`kind, title, date, url, sentiment`) remain valid, so current tests stay green.

### 5.11 `MigrationPattern.run` (new, `modules/migration.py`) — migration sharpening
- **Does:** a small deterministic detector run after `market` + `competitor` in `_stage_modules`. Reads the ledger for the co-occurrence pattern:
  1. a `market` entry indicating **game-specific** under-performance (game below benchmark, or CausalImpact "internal-driven", while the genre did **not** fall with the game), **and**
  2. a `competitor` entry that is a `competitor_event`/`influencer` rise (scope game-competitor or genre), **and**
  3. its date is **near the change-point** (`ctx.extras["changepoint"]` ± a small window).
  
  When all three hold, add a derived ledger entry: `"likely player migration to {competitor} — game-specific decline coincides with {influencer}'s {date} boost of {competitor}"`, `source_type="derived"`, `strength` = `med` if all three strong else `low`, with the standing **caveat**: *"user-level migration unconfirmed — requires cross-game data."* If the pattern does not hold, add nothing.
- **Deps:** the ledger, `ctx.extras["changepoint"]`. Pure ledger-reading logic → fully unit-testable, no network.
- **Why a detector, not a prompt:** keeps the migration inference explicit, deterministic, and testable; synthesis then naturally surfaces the derived entry.

### 5.12 Game identity — real title (extend `schema/profile.py` + onboarding)
- **Problem:** `GameProfile.name` is the CSV-derived key (e.g. `"Universe-9980885306- Day 1 retention…"`), **not** the game's real title (`"[ALPHA] UGC Anime Face Creator"`). A game-specific influencer/competitor search keyed on the CSV filename finds nothing — breaking links 2–3 of the migration question for the game itself.
- **Does:** add an **optional** `title: str | None` to `GameProfile`. Populate it at onboarding when a Roblox universe id is detectable in the profile name/config (live `games.roblox.com/v1/games?universeIds=…` lookup → `name`), or via `config set` / an admin field. `CompetitorSignals` uses `profile.title or profile.name`.
- **Fallback:** when no reliable title exists, the social provider runs **genre-scoped only** (genre buzz + competitor-substitution within the genre still work); game-specific search is skipped rather than searching a garbage string.
- **Deps:** the existing Roblox lookup pattern; additive optional field (no migration of stored profiles required — absent `title` ⇒ fallback).

## 6. Data shapes

```jsonc
// benchmark payload (stored under kind="benchmark", payload[metric])
{ "metric": "retention_d1", "low": 0.12, "high": 0.19, "median": 0.15,
  "unit": "fraction", "source": "Roblox genre benchmarks",
  "confidence": "med", "citations": ["https://…"], "summary": "…" }

// social event (SocialSignalProvider.events item)
{ "date": "2026-06-04", "kind": "influencer", "scope": "game",
  "entity": "SomeYouTuber (3M subs)", "reach": "1.2M views", "url": "https://…",
  "summary": "Featured competitor 'X' in a 06-04 video", "sentiment": 0.4,
  "title": "SomeYouTuber featured 'X'" }

// migration entry (derived)
{ "module": "migration", "claim": "likely player migration to 'X' — …",
  "value": "timing match @ change-point", "source_type": "derived",
  "strength": "med", "timeframe": "<start>..<end>" }
```

## 7. The migration question (explicit)

**Question:** *"Do my users move to another game because it got famous via an influencer?"*

The causal chain has four links; the design establishes three and is explicit about the fourth:

| Link | Established by | Status |
|---|---|---|
| 1. My metric dropped, and it's **game-specific** not market-wide | `anomaly` + `market` benchmark (Leg 1) | ✅ |
| 2. A competitor got famous in the same window | `SocialSignalProvider` competitor-substitution prompt (Leg 2) | ✅ |
| 3. It was **influencer-driven**, timing aligns with the change-point | Leg 2 dated event + `MigrationPattern` timing check | ✅ |
| 4. **My specific users moved to it** | — requires cross-game user-level overlap | ❌ unobservable from first-party data |

Links 2–3 (game-specific search) depend on having the **real game title** (§5.12); without it, the design still answers the genre-level form ("is the genre being pulled by an influencer-boosted competitor?") via genre-scoped search.

Output is therefore a **ranked, cited hypothesis** ("game-specific decline + competitor's influencer-driven rise + timing match → likely migration, confidence X") with the explicit caveat that user-level migration is unconfirmed. This matches professional practice (correlation + mechanism + timing; never proof from correlation).

## 8. Degradation & error handling

- Every web call goes through `research_json` → returns `None`/`[]` on failure; no exception escapes.
- `MarketBenchmark`, `CompetitorSignals` already wrap their feed calls in try/except (gap entry, not crash); the new benchmark-comparison block is likewise guarded.
- `MigrationPattern` is pure ledger logic; if inputs are missing it simply adds nothing.
- Low-confidence / citation-less benchmarks are hedged ("approximate") and down-strengthed, never dropped silently.

## 9. Caching & config

- **Benchmark:** cached under `(platform, genre, "benchmark")`, 7-day TTL via existing `is_fresh`; refresher short-circuits when fresh.
- **Social signals:** cached by `(game, genre, start, end)` under `cache_dir/signals` (reuse `CachedFetcher` pattern), short TTL (e.g. 24h) so repeated drilldowns don't re-bill Perplexity.
- **Config (admin-settable via `config set`):** `benchmark_mode` (existing; gates crawl), `perplexity_api_key` (existing), optional `signals_mode` (new; defaults to follow `benchmark_mode`). Platform/genre come from the (now corrected) profile.

## 10. Testing strategy (TDD — failing test first, all offline)

- `research_json`: cited dict on valid JSON; `None` on unparseable / on `answer_fn` raising.
- `WebSearchBenchmarkProvider.metric_benchmark`: `unit:"percent"` → normalized fractions + citations; unparseable → `None`.
- `BenchmarkStore`: `put/get_benchmark` round-trip; multiple metrics coexist; `is_fresh` honored.
- `BenchmarkRefresher`: `refresh(..., metric=…)` with a fake web provider stores a retrievable benchmark; `metric=None` unchanged.
- `MarketBenchmark`: game value below range → "below/underperforming" external entry with numbers + citation; within → "in line"; no benchmark → existing fallback (existing tests green).
- `SocialSignalProvider.events`: fake JSON list → scope/kind-tagged events, window-filtered; unparseable → `[]`.
- `DynamicSignals`: with key + mode → uses social provider; without → fixture/template fallback.
- `CompetitorSignals`: game-scoped influencer event → external entry citing entity/date; genre-scoped → market-context entry; empty → existing gap entry (existing test green).
- `MigrationPattern`: pattern present (game-specific market entry + competitor influencer rise near change-point) → derived migration entry with caveat; any link missing → no entry.
- Game identity: `CompetitorSignals` passes `profile.title` when set, else `profile.name`; provider runs genre-scoped only when no title (no game-specific query emitted).

## 11. Phasing

- **M1 — Quantitative benchmark (Leg 1):** §5.1–5.7. Independently shippable; immediately upgrades the `market` leg.
- **M2 — Influencer/social signals + migration (Leg 2 + detector):** §5.8–5.12 (includes the optional game-title field). Builds on the shared `research_json` from M1.

Each milestone is a self-contained set of TDD units.

## 12. Future upgrade path (out of current scope)

- **Cross-game / panel data** (Roblox first-party analytics, Sensor Tower-style estimates) — the only way to move link 4 from hypothesis toward measurement, and to add **quantitative competitor trends** (a competitor's actual DAU/CCU curve) alongside the qualitative influencer signal.
- Tiered structured benchmark sources (scrape Roblox genre-benchmark percentiles directly).
- Harden the remaining unguarded `causal_counterfactual` call in `MarketBenchmark` (Bug 6) as a separate robustness pass.
