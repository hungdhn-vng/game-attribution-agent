# Game Attribution Agent — Pitch Deck

On-brand reveal.js deck for the GreenNode Claw-a-thon 2026 (Data Analysis track).
Self-contained and **offline-safe** — reveal.js and the Geist fonts are vendored, all slides
are inline, and charts are inline SVG. No network needed to present.

## Present
- **Double-click `index.html`** (works fully offline), or `npm run serve` then open http://localhost:3000.
- Arrow keys / **Space** to advance; fragments reveal on click.
- **S** — speaker view (current + next slide + talk-track notes).
- **F** — fullscreen · **Esc** — slide overview · **B** — black the screen.
- 14 slides, ~7–10 min. Light theme by default.

## Export to PDF (one page per slide)
Reliable method (uses Playwright; install once in this dir):
```bash
npm i -D @playwright/test && npx playwright install chromium
node tools/pdf.mjs            # writes gaa-deck.pdf (14 pages)
```
Quick fallback (no install): open `index.html?print-pdf` in Chrome → Print → Save as PDF
(Landscape · margins None · Background graphics ON). Note: dense slides can split across pages
with the browser print path; `tools/pdf.mjs` avoids that.

## Refresh the live-app screenshots (slide 13)
```bash
npm i -D @playwright/test && npx playwright install chromium   # if not already
node tools/capture.mjs        # writes assets/screenshots/{chat,dossier}.png from the live app
```

## What's where
- `index.html` — all 14 slides, inline (so `file://` double-click works — no fetch/CORS)
- `theme/gaa.css` — "Bold Keynote" theme: Bricolage Grotesque display + IBM Plex Mono/Sans, full-bleed blue/amber color panels (blue = internal / amber = market)
- `assets/screenshots/` — real captures from the live app
- `assets/img/qr.png` — QR to the live app
- `tools/` — `capture.mjs` (screenshots), `pdf.mjs` (PDF export)
- `vendor/` — reveal.js + the vendored fonts (frozen, offline)

## The story (14 slides)
Demo-first: title → problem → ask → **dossier (wow)** → "would you trust an LLM?" → trust chain →
then the dossier is peeled apart, one layer per slide (anomaly · internal-vs-market · segment ·
confidence · honesty) → architecture → **proof (real, live)** → close.
The walkthrough's anchor numbers (Roblox DAU −22%) are illustrative; the live app runs on real data.
