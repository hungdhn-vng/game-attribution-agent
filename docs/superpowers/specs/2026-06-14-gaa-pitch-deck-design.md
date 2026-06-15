# GAA Pitch Deck — Design

**Status:** Approved design (pre-implementation)
**Date:** 2026-06-14
**Topic:** Presentation deck for the Game Attribution Agent (GreenNode Claw-a-thon 2026, Data Analysis track)

---

## 1. Summary

A self-contained, on-brand **reveal.js HTML deck** that pitches the Game Attribution Agent to a
**technically literate hackathon audience**, balancing a "wow" live-demo opening with the
engineering rigor that is GAA's real differentiator. The deck reuses GAA's own design language
(Geist typography, monochrome canvas, **blue = internal cause / amber = market cause**, card
aesthetic, monospace citation chips) so it reads as a continuation of the product, not a separate
artifact.

The narrative is **Arc A — "magic, then mechanism"**: open cold with the live demo, hinge on the
honest objection ("would you trust an LLM with your numbers?"), then peel the resulting dossier
apart **one layer per slide**, each layer revealing the deterministic method behind it (the
dossier-anatomy structure folded into the rigor section).

## 2. Decisions locked during brainstorming

| Dimension | Decision |
|---|---|
| Audience | Technical deep-dive (engineering / data-science judges) |
| Format | On-brand HTML deck, **reveal.js** |
| Length | **14 slides**, ~7–10 min |
| Emphasis | Balanced — wow + rigor |
| Narrative arc | **Arc A (demo-first)** with the **dossier-anatomy layer-walk folded into the rigor section** |
| Demo anchor | Roblox **"is it us or the market?"** — a ~−22% DAU dip that proves mostly genre-wide |
| Default theme | **Light** (dark variables retained but not shipped as a toggle — out of scope) |
| Demo visuals | **Captured from the live Vercel app** (headless browser), with the in-deck recreation as an offline fallback |
| Build extras | **QR code** to the live app + **PDF leave-behind** export |

## 3. Visual design system

Derived directly from `frontend/app/globals.css` and `src/gaa/core/render/templates/report.html.j2`:

- **Fonts:** Geist (sans) for everything; Geist Mono for citations, evidence IDs, code. Both
  **vendored locally** as woff2 — no webfont network dependency.
- **Light theme (default):** bg `oklch(0.985 0 0)` (~#fafafa), fg `oklch(0.12 0 0)`, card `#fff`,
  muted `#8a8a8a`, border `#e7e5e4`.
- **Semantic accents (the brand's core signal):** internal = blue `#2563eb`, market = amber
  `#d97706` (chart variants `#3b82f6` / `#f59e0b`), scenario/neutral = gray `#9ca3af`.
- **Components carried from the dossier:** uppercase micro-label (10px, letter-spacing .09em, 600
  weight, muted); confidence pill with a blue dot; cause tags (Internal=blue, Market=amber,
  neutral=muted); monospace citation chip (e.g. `E2, E5`); card = 12px radius, 1px border, subtle
  shadow.
- **Headings:** tight letter-spacing (−0.025em), line-height 1.2. Body line-height ~1.55.
- **Motion:** spring easing `cubic-bezier(0.22, 1, 0.36, 1)` for fragment reveals.

A light/dark mockup of the title + "you vs market" slide was validated in the visual companion;
the look was approved.

## 4. Slide-by-slide outline (14 slides)

The Roblox "−22% DAU — is it us or the market?" case runs as one continuous story across the deck.
Illustrative numbers (−22%, v2.3 / mobile-SEA) are coherent and clearly not claimed as a real run
unless matched to one at build time.

1. **Title** — "Game Attribution Agent." Kicker: *GreenNode Claw-a-thon 2026 · Data Analysis*.
   One-liner: *"The AI analyst that explains why your game's metrics moved — and shows its
   evidence."* Footer cues: internal vs market · every claim cited · scenarios, not decisions.
2. **The problem** — "A number moved. Now the fire drill starts." Days lost arguing *our update?*
   vs *genre slump?*, hand-pulled dashboards, no audit trail. The gap (inline): **BI dashboards
   show *what*, never *why*; LLM copilots will *say* why but hallucinate the numbers.**
3. **Demo: we just ask** — the chat. *"What's going on with my Roblox game's DAU this week?"* The
   activity strip lights up: `plan → crawl → modules → synth → render`.
4. **Demo: the dossier appears** *(the wow)* — full dossier card lands: headline, confidence pill,
   you-vs-market overlay, cited cause-cards, confidence matrix. No explanation yet.
5. **The hinge** — "But would you trust an LLM with your numbers?" The honest objection, stated
   bluntly. → doorway into rigor.
6. **The answer: the trust chain** — *The LLM never invents a finding.* Flow diagram:
   **deterministic tools → evidence ledger (append-only) → synthesizer → self-consistency gate →
   citation validator → dossier.** LLM only routes intent, maps columns, writes narrative. Citation
   validator is a hard gate.
   *— then the dossier is peeled apart, one layer per slide —*
7. **Layer 1 · Anomaly** — change-point (ruptures/PELT) finds *when* it broke; STL quantifies *how
   anomalous*. Timeseries with anomaly window → ledger E1, E2.
8. **Layer 2 · Internal vs market** *(the differentiator)* — CausalImpact-style BSTS
   **counterfactual** vs a genre benchmark; the overlay chart indexed to 100. *"What would DAU have
   been without the event? The gap is the true internal effect."* Mostly market (amber), a slice
   internal (blue). One line on live benchmark tiers (snapshot → Roblox/Steam crawl → Perplexity).
9. **Layer 3 · Segment root-cause** — Adtributor pins the *internal* residual to a
   version/region/cohort as a citable % contribution. Cited cause-cards.
10. **Layer 4 · Dual-axis confidence** — the confidence matrix (likelihood × evidence quality).
    *"Most tools give one number; we give two."*
11. **Layer 5 · Honesty / abstention** — thin evidence → lower confidence, stated assumptions &
    gaps; self-consistency gate (N samples agree) + citation validator reject shaky claims.
    *"Scenarios, not decisions — the human decides."*
12. **Architecture** — FastAPI **Custom Agent** on GreenNode AgentBase (one image: `/chat`,
    `/invocations`, `/runs/<id>` dossier, `/health`). Resumable budget-sliced pipeline. Next.js
    frontend on Vercel. Qwen 3.5 27B via MaaS for routing/mapping/narration; Perplexity sonar
    opt-in. Deterministic analytics in-process. System diagram.
13. **Proof — real, not a mockup** — 177 passing tests · TDD throughout · engine verified
    end-to-end with a fake LLM · deployed live on AgentBase + Vercel · real Roblox/Steam benchmark
    crawl. Live link + **QR**.
14. **Close — roadmap & ask** — recap one-liner. Next: multi-game portfolio views, tool-promotion
    (a toolbox that grows), admin-only hardening. Thank-you + link.

## 5. Technical architecture

New self-contained top-level directory; nothing else in the repo is touched.

```
deck/
├── index.html            # the reveal.js deck (all 14 <section>s)
├── theme/gaa.css          # custom theme from dossier tokens (light default; dark vars retained)
├── assets/
│   ├── charts/            # recreated signature visuals (inline SVG / HTML-CSS)
│   ├── screenshots/       # captured from the live Vercel app
│   └── img/               # wordmark, QR code
├── vendor/
│   ├── reveal/            # reveal.js dist (vendored — offline-safe)
│   └── fonts/             # Geist + Geist Mono woff2
└── README.md              # how to present (keys), export to PDF, capture refresh
```

- **reveal.js vendored locally** (installed via npm, dist copied into `vendor/reveal/`) — opens by
  double-clicking `index.html` or `npx serve deck`; **no CDN/wifi dependency** at the venue.
- **Signature visuals recreated natively** as inline SVG + HTML/CSS, theme-aware, crisp at any
  projector resolution. Reveal **fragments** animate the layer-by-layer reveals (draw the genre
  line → reveal the counterfactual gap; light up each trust-chain stage in sequence). The "dossier
  appears" slide is adapted from the prior faithful recreation at
  `.superpowers/brainstorm/59430-1781422791/content/dossier-full.html`.
- **Speaker notes** (reveal notes plugin, press `S`) carry a per-slide talk track.
- **PDF leave-behind** via reveal's `?print-pdf` + browser print-to-PDF; documented in the deck
  README.
- **QR code** to `https://game-attribution-agent.vercel.app` generated at build time (static PNG/SVG
  in `assets/img/`), shown on slides 13 and 14.

## 6. Demo & proof asset strategy

- The **Vercel frontend is live** (verified HTTP 200). Demo screenshots (chat view + dossier) are
  **captured from the live app via a headless browser** (Playwright) and embedded in slides 3–4;
  the live URL + QR appear on slides 13–14.
- The **AgentBase `/health` did not respond cleanly** during design (gateway "no Route matched").
  Therefore: the in-deck **recreation is the offline fallback** for slides 3–4, and a **recorded
  short screen-capture** of a successful run is recommended as the on-stage safety net. The deck
  must present fully **without any network**.
- Existing repo assets to evaluate for reuse: `frontend/public/preview.png`,
  `frontend/public/images/demo-thumbnail.png`.

## 7. Verification

- Step through all 14 slides at 16:9; confirm fragments fire in order and no content clips.
- Test **PDF export** (`?print-pdf`) renders all slides cleanly.
- Test **fully offline** (disable network) — fonts, reveal.js, charts, screenshots all load locally.
- Confirm the QR resolves to the live app.
- Sanity-check legibility on a projector aspect / low-contrast environment.

## 8. Out of scope

- Dark-mode toggle (light is the shipped default; dark CSS vars retained but not wired to a key).
- Embedding a live/iframed real `report.html` (recreation is used instead; revisit only if a real
  run with keys is desired).
- Any change to `frontend/` or `src/` — the deck is additive and isolated.
- Speaker rehearsal / timing coaching (the deck supports it via notes; not a build deliverable).

## 9. Open items resolved at build time

1. Capture fresh screenshots from the live app (Playwright); fall back to recreation if the run
   path is degraded.
2. Match illustrative Roblox numbers to a real run if one is provided; otherwise keep the coherent
   invented case, clearly not claimed as real.
3. Confirm whether `preview.png` / `demo-thumbnail.png` are usable or should be replaced by fresh
   captures.
