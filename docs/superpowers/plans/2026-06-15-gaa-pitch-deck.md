# GAA Pitch Deck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained, on-brand reveal.js pitch deck for the Game Attribution Agent that opens offline by double-clicking, exports to PDF, and tells the demo-first "magic, then mechanism" story.

**Architecture:** A new isolated top-level `deck/` directory. reveal.js + Geist fonts are vendored locally (no CDN). All 14 slides live inline in one `index.html` (so `file://` double-click works — no external fetches). A single custom theme `theme/gaa.css` carries GAA's dossier tokens. The three signature visuals are hand-built inline SVG; demo screenshots are captured from the live Vercel app with the in-deck recreation as the offline fallback.

**Tech Stack:** reveal.js (vendored), Geist + Geist Mono woff2 (vendored), plain HTML/CSS/SVG, `qrcode` CLI (QR), Playwright (screenshot capture, already in `frontend/`), decktape or Chrome print (PDF).

**Verification model:** A deck is verified visually and functionally, not by unit tests. Each task ends with a concrete browser/CLI check ("open `deck/index.html`, confirm X") and a commit. Treat the check as the test: do not mark a task done until its check passes.

**Reference material (read before starting):**
- Spec: `docs/superpowers/specs/2026-06-14-gaa-pitch-deck-design.md`
- Brand tokens: `frontend/app/globals.css` (`:root` light vars) and `src/gaa/core/render/templates/report.html.j2` (dossier component CSS)
- Chart logic to mirror: `src/gaa/core/render/charts.py` (overlay = indexed-to-100 two-line; matrix = likelihood×evidence scatter; internal `#3b82f6` / market `#f59e0b` / scenario `#9ca3af`)
- Prior dossier recreation to adapt for slide 4: `.superpowers/brainstorm/59430-1781422791/content/dossier-full.html`
- Product copy source of truth: `README.md`
- Live app (HTTP 200): `https://game-attribution-agent.vercel.app`

**Branch:** all work on `deck/gaa-pitch-deck` (already created; the spec commit is its first commit).

---

## File Structure

```
deck/
├── index.html              # the whole deck — all 14 <section>s inline
├── theme/gaa.css           # brand theme: tokens, typography, slide components
├── assets/
│   ├── img/
│   │   ├── qr.png          # QR to the live app (generated)
│   │   └── wordmark.svg    # optional GAA wordmark (text fallback if skipped)
│   └── screenshots/        # captured from the live app
│       ├── chat.png
│       └── dossier.png     # if a clean run is capturable; else recreation is used
├── tools/
│   └── capture.mjs         # Playwright screenshot script
├── vendor/
│   ├── reveal/             # reveal.js dist + notes plugin (copied from npm)
│   └── fonts/              # geist + geist-mono woff2 (copied from npm)
├── package.json            # dev deps for vendoring/build only (reveal.js, geist, qrcode)
└── README.md               # present / export / refresh-capture instructions
```

Responsibilities: `index.html` = structure + content; `theme/gaa.css` = all styling (the single source of brand truth); `tools/capture.mjs` = asset capture (run rarely); `vendor/` = frozen third-party. Slides are inline (not external `data-src` partials) deliberately — external section loading fails under `file://` CORS, breaking double-click-to-open.

---

## Task 1: Scaffold + vendor reveal.js and fonts + bootable shell

**Files:**
- Create: `deck/package.json`, `deck/index.html`, `deck/theme/gaa.css` (stub), `deck/vendor/reveal/*`, `deck/vendor/fonts/*`
- Create: `deck/.gitignore` (ignore `node_modules/`)

- [ ] **Step 1: Create `deck/package.json`**

```json
{
  "name": "gaa-deck",
  "private": true,
  "version": "1.0.0",
  "description": "Game Attribution Agent — pitch deck (reveal.js, vendored).",
  "scripts": {
    "serve": "npx --yes serve -l 3000 .",
    "pdf": "npx --yes decktape reveal http://localhost:3000/?print-pdf gaa-deck.pdf"
  },
  "devDependencies": {
    "reveal.js": "^5.1.0",
    "geist": "^1.3.1",
    "qrcode": "^1.5.4"
  }
}
```

- [ ] **Step 2: Install dev deps (used only to vendor assets)**

Run:
```bash
cd deck && npm install
```
Expected: `node_modules/reveal.js`, `node_modules/geist`, `node_modules/qrcode` present.

- [ ] **Step 3: Vendor reveal.js dist + notes plugin into the repo**

Run:
```bash
cd deck
mkdir -p vendor/reveal/dist vendor/reveal/plugin
cp -R node_modules/reveal.js/dist/* vendor/reveal/dist/
cp -R node_modules/reveal.js/plugin/notes vendor/reveal/plugin/notes
ls vendor/reveal/dist/reveal.js vendor/reveal/dist/reveal.css vendor/reveal/plugin/notes/notes.js
```
Expected: all three paths exist (no "No such file").

- [ ] **Step 4: Vendor Geist + Geist Mono woff2 into the repo**

Run (locate the woff2 files the `geist` package ships, then copy them):
```bash
cd deck
mkdir -p vendor/fonts
find node_modules/geist -name '*.woff2' -exec cp {} vendor/fonts/ \;
ls vendor/fonts
```
Expected: at least one `Geist*.woff2` and one `GeistMono*.woff2` (variable fonts are fine). If the package only ships variable fonts, note the exact filenames printed — they're used in `gaa.css` `@font-face` in Task 2.

- [ ] **Step 5: Create `deck/.gitignore`**

```
node_modules/
gaa-deck.pdf
```

- [ ] **Step 6: Create the bootable `deck/index.html` shell with one placeholder slide**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Game Attribution Agent — Claw-a-thon 2026</title>
  <link rel="stylesheet" href="vendor/reveal/dist/reveal.css" />
  <link rel="stylesheet" href="theme/gaa.css" />
</head>
<body>
  <div class="reveal">
    <div class="slides">
      <section data-state="title">
        <p class="kicker">GreenNode Claw-a-thon 2026 · Data Analysis</p>
        <h1 class="deck-title">Game Attribution Agent</h1>
        <p class="lead">Scaffold OK — replace in later tasks.</p>
      </section>
    </div>
  </div>
  <script src="vendor/reveal/dist/reveal.js"></script>
  <script src="vendor/reveal/plugin/notes/notes.js"></script>
  <script>
    Reveal.initialize({
      hash: true,
      slideNumber: "c/t",
      width: 1280, height: 720, margin: 0.06,
      controls: true, progress: true,
      transition: "fade",
      plugins: [RevealNotes],
    });
  </script>
</body>
</html>
```

- [ ] **Step 7: Verify it boots offline**

Run: `open deck/index.html` (or double-click). Then **turn off wifi** and reload.
Expected: the title slide renders, slide number shows `1/1`, no console 404s for reveal.css/reveal.js. (Fonts/theme are stubbed; styling lands in Task 2.)

- [ ] **Step 8: Commit**

```bash
git add deck/package.json deck/index.html deck/theme/gaa.css deck/.gitignore deck/vendor
git commit -m "feat(deck): scaffold reveal.js shell with vendored reveal + fonts"
```

---

## Task 2: Brand theme — `deck/theme/gaa.css`

**Files:**
- Modify: `deck/theme/gaa.css` (replace stub with the full theme)

Build the single source of brand truth. Light is the default; dark vars are defined under `[data-theme="dark"]` but no toggle ships (per spec §8). Use the exact font filenames found in Task 1 Step 4 for the `@font-face` `src`.

- [ ] **Step 1: Write the full theme**

```css
/* ---- Fonts (vendored; update filenames to match vendor/fonts/) ---- */
@font-face { font-family:"Geist"; src:url("../vendor/fonts/Geist[wght].woff2") format("woff2");
  font-weight:100 900; font-display:swap; }
@font-face { font-family:"Geist Mono"; src:url("../vendor/fonts/GeistMono[wght].woff2") format("woff2");
  font-weight:100 900; font-display:swap; }

/* ---- Tokens (from frontend/app/globals.css + report.html.j2) ---- */
:root{
  --bg:oklch(0.985 0 0); --fg:oklch(0.12 0 0); --card:#ffffff;
  --muted:oklch(0.58 0 0); --border:oklch(0.9 0 0); --secondary:oklch(0.965 0 0);
  --blue:#2563eb; --blue-bg:#eff6ff; --blue-bd:#dbeafe;
  --amber:#b45309; --amber-ln:#d97706; --amber-bg:#fffbeb; --amber-bd:#fde68a;
  --warn-bg:#fffbeb; --warn-bd:#fde68a; --warn-fg:#92400e;
  --scenario:#9ca3af;
  --shadow:0 1px 3px rgba(0,0,0,.05),0 1px 1px rgba(0,0,0,.03);
  --ease-spring:cubic-bezier(0.22,1,0.36,1);
}
[data-theme="dark"]{
  --bg:oklch(0.195 0 0); --fg:oklch(0.94 0 0); --card:oklch(0.225 0 0);
  --muted:oklch(0.6 0 0); --border:oklch(0.27 0 0); --secondary:oklch(0.26 0 0);
  --blue:#60a5fa; --blue-bg:rgba(96,165,250,.13); --blue-bd:rgba(96,165,250,.32);
  --amber:#fbbf24; --amber-ln:#f59e0b; --amber-bg:rgba(251,191,36,.12); --amber-bd:rgba(251,191,36,.3);
}

/* ---- Reveal base ---- */
.reveal{ font-family:"Geist",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:30px; color:var(--fg); -webkit-font-smoothing:antialiased; }
.reveal-viewport{ background:var(--bg); }
.reveal .slides{ text-align:left; }
.reveal .slides section{ height:100%; }
.reveal h1,.reveal h2,.reveal h3{ color:var(--fg); letter-spacing:-0.025em; line-height:1.15;
  margin:0 0 .3em; text-transform:none; font-weight:600; }
.reveal h1{ font-size:1.9em; } .reveal h2{ font-size:1.35em; } .reveal h3{ font-size:1.05em; }
.reveal p{ line-height:1.55; }
.reveal a{ color:var(--blue); }
.reveal ::selection{ background:rgba(37,99,235,.18); }

/* ---- Brand components ---- */
.kicker{ font-size:.46em; letter-spacing:.16em; text-transform:uppercase; color:var(--muted);
  font-weight:600; margin:0 0 .6em; }
.deck-title{ font-size:2.5em; letter-spacing:-0.03em; }
.lead{ font-size:.72em; color:var(--muted); max-width:24ch; }
.microlabel{ font-size:.34em; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);
  font-weight:600; margin:0 0 .5em; }
.eyebrow{ font-size:.4em; letter-spacing:.12em; text-transform:uppercase; color:var(--blue);
  font-weight:600; margin:0 0 .4em; }

.card{ background:var(--card); border:1px solid var(--border); border-radius:14px;
  padding:.7em .8em; box-shadow:var(--shadow); }

.pill{ display:inline-flex; align-items:center; gap:.4em; font-size:.42em; font-weight:500;
  padding:.25em .7em; background:var(--secondary); border:1px solid var(--border); border-radius:9px; }
.pill .dot{ width:.5em; height:.5em; border-radius:50%; background:var(--blue); }

.tag{ display:inline-block; font-size:.36em; font-weight:600; padding:.15em .6em; border-radius:6px;
  letter-spacing:.02em; }
.tag.i{ background:var(--blue-bg); color:var(--blue); border:1px solid var(--blue-bd); }
.tag.m{ background:var(--amber-bg); color:var(--amber); border:1px solid var(--amber-bd); }
.tag.n{ background:var(--secondary); color:var(--muted); border:1px solid var(--border); }
.cite{ font-family:"Geist Mono",ui-monospace,monospace; font-size:.34em; color:var(--muted);
  background:var(--secondary); border:1px solid var(--border); padding:.1em .5em; border-radius:5px; }

.cause{ border-left:3px solid; padding:.3em 0 .3em .55em; margin:.45em 0; }
.cause.i{ border-color:var(--blue); } .cause.m{ border-color:var(--amber-ln); }
.cause p{ margin:0 0 .25em; font-size:.6em; }

.gaps{ background:var(--warn-bg); border:1px solid var(--warn-bd); border-radius:14px; padding:.7em .9em; }
.gaps .microlabel{ color:var(--warn-fg); }

.mono{ font-family:"Geist Mono",ui-monospace,monospace; }
.muted{ color:var(--muted); }

/* layout helpers */
.row{ display:flex; gap:1em; align-items:center; }
.cols{ display:grid; grid-template-columns:1fr 1fr; gap:1em; align-items:center; }
.stack-center{ display:flex; flex-direction:column; justify-content:center; height:100%; }
.center{ text-align:center; align-items:center; }
.big{ font-size:1.5em; font-weight:600; letter-spacing:-0.02em; }

/* reveal fragment easing on brand */
.reveal .slides section .fragment{ transition:all .35s var(--ease-spring); }
```

- [ ] **Step 2: Update the `@font-face` `src` filenames**

Edit the two `@font-face` `src:url(...)` to exactly match the files in `deck/vendor/fonts/` (from Task 1 Step 4). E.g. if the file is `Geist-Variable.woff2`, use that.

- [ ] **Step 3: Verify the title slide is on-brand**

Run: reload `deck/index.html`.
Expected: Geist font renders (not Times/Arial), near-white background, near-black title, muted uppercase kicker. Confirm in DevTools that the woff2 files load (Network tab, no 404).

- [ ] **Step 4: Commit**

```bash
git add deck/theme/gaa.css
git commit -m "feat(deck): brand theme from GAA dossier tokens (Geist, blue/amber, cards)"
```

---

## Task 3: Build the three signature SVG visuals (preview harness)

**Files:**
- Create: `deck/assets/charts/_preview.html` (throwaway harness, kept for reference)
- These SVGs are pasted inline into slides in Tasks 5–7. Build and eyeball them in isolation first.

The SVGs use `currentColor` and CSS vars so they theme automatically. Coordinates mirror `charts.py` semantics: overlay indexed to 100, both lines dipping in the back half (market dip), the blue "you" line dipping further (the internal slice); matrix axes Weak→Strong × Unlikely→Very likely.

- [ ] **Step 1: Create the preview harness with all three SVGs**

```html
<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="../../theme/gaa.css">
<style>body{background:var(--bg);padding:24px;display:grid;gap:20px;grid-template-columns:1fr 1fr}
 .card{max-width:560px}</style></head><body>

<!-- OVERLAY: you vs market, indexed to 100 -->
<div class="card"><p class="microlabel">You vs the market · indexed to 100</p>
<svg viewBox="0 0 480 220" width="100%" font-family="Geist">
  <rect x="300" y="20" width="160" height="160" fill="#ef4444" opacity="0.06"/>
  <line x1="40" y1="180" x2="460" y2="180" stroke="var(--border)"/>
  <line x1="40" y1="20" x2="40" y2="180" stroke="var(--border)"/>
  <text x="44" y="34" font-size="11" fill="var(--muted)">100</text>
  <polyline fill="none" stroke="var(--amber-ln)" stroke-width="3"
    points="50,60 150,56 250,66 320,108 400,120 455,118"/>
  <polyline fill="none" stroke="var(--blue)" stroke-width="3.4"
    points="50,52 150,48 250,60 320,128 400,150 455,146"/>
  <!-- counterfactual gap annotation (fragment in-slide) -->
  <line class="cf" x1="455" y1="118" x2="455" y2="146" stroke="var(--blue)" stroke-dasharray="3 3"/>
  <circle cx="455" cy="146" r="4" fill="var(--blue)"/><circle cx="455" cy="118" r="3.5" fill="var(--amber-ln)"/>
  <text x="58" y="200" font-size="11" fill="var(--muted)">Jun 1</text>
  <text x="420" y="200" font-size="11" fill="var(--muted)">Jun 14</text>
</svg>
<div class="row" style="font-size:.5em;color:var(--muted);gap:1.2em;margin-top:.4em">
  <span><b style="color:var(--blue)">—</b> Your DAU (indexed)</span>
  <span><b style="color:var(--amber-ln)">—</b> Genre (indexed)</span></div>
</div>

<!-- CONFIDENCE MATRIX -->
<div class="card"><p class="microlabel">Confidence matrix · likelihood × evidence</p>
<svg viewBox="0 0 480 260" width="100%" font-family="Geist">
  <line x1="70" y1="220" x2="460" y2="220" stroke="var(--border)"/>
  <line x1="70" y1="20" x2="70" y2="220" stroke="var(--border)"/>
  <!-- x ticks -->
  <text x="140" y="240" font-size="11" fill="var(--muted)" text-anchor="middle">Weak</text>
  <text x="265" y="240" font-size="11" fill="var(--muted)" text-anchor="middle">Moderate</text>
  <text x="390" y="240" font-size="11" fill="var(--muted)" text-anchor="middle">Strong</text>
  <!-- y ticks -->
  <text x="62" y="200" font-size="10" fill="var(--muted)" text-anchor="end">Unlikely</text>
  <text x="62" y="150" font-size="10" fill="var(--muted)" text-anchor="end">Possible</text>
  <text x="62" y="95" font-size="10" fill="var(--muted)" text-anchor="end">Likely</text>
  <text x="62" y="45" font-size="10" fill="var(--muted)" text-anchor="end">Very likely</text>
  <!-- points: market (strong, likely), internal slice (moderate, possible), scenario (weak, possible) -->
  <circle cx="390" cy="95" r="9" fill="var(--amber-ln)"/><text x="390" y="80" font-size="10" fill="var(--fg)" text-anchor="middle">Genre dip</text>
  <circle cx="265" cy="150" r="9" fill="var(--blue)"/><text x="265" y="135" font-size="10" fill="var(--fg)" text-anchor="middle">v2.3 update</text>
  <circle cx="140" cy="150" r="9" fill="var(--scenario)"/><text x="140" y="135" font-size="10" fill="var(--fg)" text-anchor="middle">Seasonality</text>
</svg></div>

<!-- TIMESERIES with anomaly window + change-point -->
<div class="card"><p class="microlabel">DAU over time · change-point detected</p>
<svg viewBox="0 0 480 200" width="100%" font-family="Geist">
  <rect x="300" y="15" width="160" height="150" fill="#ef4444" opacity="0.06"/>
  <line x1="40" y1="165" x2="460" y2="165" stroke="var(--border)"/>
  <polyline fill="none" stroke="var(--blue)" stroke-width="3"
    points="50,60 110,56 170,62 230,58 300,64 300,64 360,120 420,140 455,138"/>
  <line x1="300" y1="15" x2="300" y2="165" stroke="var(--muted)" stroke-dasharray="4 4"/>
  <text x="306" y="28" font-size="10" fill="var(--muted)">change-point · Jun 8</text>
</svg></div>

</body></html>
```

- [ ] **Step 2: Verify the visuals read correctly**

Run: `open deck/assets/charts/_preview.html`.
Expected: overlay shows two lines both dipping after Jun 8, the blue (you) dipping further, with a dashed gap at the right edge = the internal effect; the matrix shows amber "Genre dip" high-right (likely/strong), blue "v2.3 update" mid, gray "Seasonality" low-left; the timeseries shows a clean break at the change-point line. Tweak coordinates until each reads at a glance.

- [ ] **Step 3: Commit**

```bash
git add deck/assets/charts/_preview.html
git commit -m "feat(deck): signature SVG visuals (overlay, confidence matrix, timeseries)"
```

---

## Task 4: Slides 1–2 (Title, Problem)

**Files:**
- Modify: `deck/index.html` (replace the placeholder `<section>`; append the second)

Slide markup pattern (used for every slide from here): each slide is one `<section>` with `class="stack-center"` unless noted; speaker notes go in `<aside class="notes">…</aside>` (filled in Task 12).

- [ ] **Step 1: Replace the placeholder with the Title slide**

```html
<section data-state="title" class="stack-center center">
  <p class="kicker">GreenNode Claw-a-thon 2026 · Data Analysis Track</p>
  <h1 class="deck-title">Game Attribution Agent</h1>
  <p class="lead" style="max-width:30ch;text-align:center">The AI analyst that explains <em>why</em> your game's metrics moved — and shows its evidence.</p>
  <p class="microlabel" style="margin-top:1.4em">internal vs market · every claim cited · scenarios, not decisions</p>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 2: Append the Problem slide**

```html
<section class="stack-center">
  <p class="eyebrow">The problem</p>
  <h2>A number moved. Now the fire drill starts.</h2>
  <p style="font-size:.7em;max-width:30ch">DAU drops 22% overnight. The team burns days arguing: <em>our last update?</em> or <em>a genre-wide slump?</em> — hand-pulling dashboards, no audit trail, no agreement.</p>
  <div class="cols" style="margin-top:.6em;font-size:.62em">
    <div class="card"><p class="microlabel">BI dashboards</p><p style="margin:0">Show you <b>what</b> happened. Never <b>why</b>.</p></div>
    <div class="card"><p class="microlabel">LLM copilots</p><p style="margin:0">Will <b>say</b> why — and hallucinate the numbers.</p></div>
  </div>
  <p class="muted" style="font-size:.55em;margin-top:.7em">Nothing answers <b>why</b>, honestly.</p>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 3: Verify**

Run: reload `deck/index.html`; arrow through slides 1→2.
Expected: title centered and on-brand; problem slide shows the two contrast cards side by side, no clipping at 1280×720.

- [ ] **Step 4: Commit**

```bash
git add deck/index.html
git commit -m "feat(deck): slides 1-2 (title, problem)"
```

---

## Task 5: Slides 3–4 (Demo: ask, then the dossier appears)

**Files:**
- Modify: `deck/index.html` (append two sections)

Slide 4 embeds the **recreated dossier** (adapt markup from `.superpowers/brainstorm/59430-1781422791/content/dossier-full.html`, restyled with `gaa.css` classes). Real screenshots replace/augment these in Task 11; build the recreation first so the deck is complete without them.

- [ ] **Step 1: Append slide 3 (the ask)**

```html
<section class="stack-center">
  <p class="eyebrow">Demo</p>
  <h2>So we just… ask.</h2>
  <div class="card" style="font-size:.62em;max-width:26ch">
    <p class="microlabel">You</p>
    <p style="margin:0">"What's going on with my Roblox game's DAU this week?"</p>
  </div>
  <div class="row" style="margin-top:.8em;font-size:.5em;color:var(--muted);gap:.5em">
    <span class="mono">plan</span><span>→</span><span class="mono">crawl</span><span>→</span>
    <span class="mono">modules</span><span>→</span><span class="mono">synth</span><span>→</span><span class="mono">render</span>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 2: Append slide 4 (the dossier — the wow)**

Build a compact dossier card reusing brand classes + the overlay SVG from Task 3. Use this structure (fill the overlay `<svg>` from Task 3 Step 1):

```html
<section data-state="dossier">
  <div class="card" style="max-width:none">
    <div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><p class="microlabel">Attribution dossier · DAU · Jun 1 – 14</p>
        <h3 style="font-size:.8em;max-width:30ch">Your −22% DAU largely tracked a genre-wide dip — mostly the market, not your update.</h3></div>
      <span class="pill"><span class="dot"></span>Likely · Strong evidence</span>
    </div>
    <div class="cols" style="margin-top:.5em">
      <div><!-- PASTE the overlay <svg> from Task 3 Step 1 here, scaled to width:100% --></div>
      <div style="font-size:.62em">
        <div class="cause m"><p>Genre-wide CCU fell ~18% the same week (market).</p>
          <span class="tag m">Market</span> <span class="tag n">Likely</span> <span class="cite">E2, E5</span></div>
        <div class="cause i"><p>v2.3 update added load time on mobile-SEA (internal).</p>
          <span class="tag i">Internal</span> <span class="tag n">Possible</span> <span class="cite">E7</span></div>
      </div>
    </div>
  </div>
  <p class="muted center" style="font-size:.5em;margin-top:.5em">It read the data, crawled the market, ran four analyses, and wrote this — every line cited.</p>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 3: Verify**

Run: reload; go to slides 3→4.
Expected: the ask slide shows the pipeline strip; the dossier slide shows the headline, confidence pill, overlay chart, and two color-coded cited cause-cards, all fitting 1280×720.

- [ ] **Step 4: Commit**

```bash
git add deck/index.html
git commit -m "feat(deck): slides 3-4 (demo ask + recreated dossier)"
```

---

## Task 6: Slides 5–6 (The hinge, the trust chain)

**Files:**
- Modify: `deck/index.html` (append two sections)
- Modify: `deck/theme/gaa.css` (add `.chain` styles)

- [ ] **Step 1: Add trust-chain styles to `gaa.css`**

```css
.chain{ display:flex; align-items:stretch; gap:.5em; flex-wrap:wrap; font-size:.5em; }
.chain .node{ background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:.5em .7em; box-shadow:var(--shadow); position:relative; }
.chain .node.llm{ border-color:var(--blue); background:var(--blue-bg); color:var(--blue); }
.chain .arrow{ align-self:center; color:var(--muted); }
.chain .node .role{ display:block; font-size:.7em; color:var(--muted); margin-top:.15em; }
```

- [ ] **Step 2: Append slide 5 (the hinge)**

```html
<section class="stack-center center" data-state="hinge">
  <p class="eyebrow">The catch</p>
  <h2 class="big" style="max-width:24ch">But would you trust an LLM with your numbers?</h2>
  <p class="muted" style="font-size:.62em;max-width:34ch;text-align:center">LLMs invent confident percentages. If an AI says revenue dropped because of one region — can you bet a roadmap on it?</p>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 3: Append slide 6 (the trust chain)**

```html
<section class="stack-center">
  <p class="eyebrow">The answer</p>
  <h2>The LLM never invents a finding.</h2>
  <div class="chain" style="margin:.6em 0">
    <div class="node">Deterministic tools<span class="role">produce facts</span></div>
    <span class="arrow">→</span>
    <div class="node">Evidence ledger<span class="role">append-only</span></div>
    <span class="arrow">→</span>
    <div class="node llm">Synthesizer<span class="role">LLM narrates</span></div>
    <span class="arrow">→</span>
    <div class="node">Self-consistency gate<span class="role">N samples agree</span></div>
    <span class="arrow">→</span>
    <div class="node">Citation validator<span class="role">hard gate</span></div>
    <span class="arrow">→</span>
    <div class="node">Dossier</div>
  </div>
  <p style="font-size:.58em;max-width:40ch">The LLM only <b>routes intent</b>, <b>maps columns</b>, and <b>writes the narrative</b>. Every number traces to a ledger entry. An uncited claim never ships.</p>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 4: Verify**

Run: reload; slides 5→6.
Expected: hinge is a single bold question; trust chain renders as a left-to-right node flow with the Synthesizer node highlighted blue (the only LLM step).

- [ ] **Step 5: Commit**

```bash
git add deck/index.html deck/theme/gaa.css
git commit -m "feat(deck): slides 5-6 (hinge + trust chain)"
```

---

## Task 7: Slides 7–11 (the five dossier layers, with fragments)

**Files:**
- Modify: `deck/index.html` (append five sections)

Each layer slide pairs a method (left) with its visual (right), and uses reveal `class="fragment"` so the visual/insight reveals on click. Paste the matching SVG from Task 3.

- [ ] **Step 1: Slide 7 — Layer 1: Anomaly (timeseries SVG)**

```html
<section>
  <p class="microlabel">Layer 1 · Anomaly</p>
  <h2>What moved — and exactly when.</h2>
  <div class="cols">
    <div style="font-size:.62em">
      <p><b>Change-point detection</b> (ruptures / PELT) finds the break: <span class="mono">Jun 8</span>.</p>
      <p class="fragment"><b>STL decomposition</b> quantifies how anomalous it is vs seasonality.</p>
      <p class="fragment"><span class="cite">→ E1, E2</span> written to the ledger.</p>
    </div>
    <div><!-- PASTE timeseries <svg> from Task 3 --></div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 2: Slide 8 — Layer 2: Internal vs market (overlay SVG, the differentiator)**

```html
<section data-state="differentiator">
  <p class="microlabel">Layer 2 · Internal vs market</p>
  <h2>Is it us — or the market?</h2>
  <div class="cols">
    <div><!-- PASTE overlay <svg> from Task 3; wrap the dashed gap line in class="fragment" --></div>
    <div style="font-size:.6em">
      <p><b>CausalImpact-style counterfactual</b> (BSTS) vs a genre benchmark.</p>
      <p class="fragment">"What <em>would</em> DAU have been without the event?" The gap is the <b>true internal effect</b>.</p>
      <p class="fragment">Most of the −22% = <span class="tag m">Market</span>. A slice = <span class="tag i">Internal</span>.</p>
      <p class="fragment muted" style="font-size:.85em">Benchmark tiers: snapshot → Roblox/Steam crawl → Perplexity.</p>
    </div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 3: Slide 9 — Layer 3: Segment root-cause**

```html
<section>
  <p class="microlabel">Layer 3 · Segment root-cause</p>
  <h2>Of the part that <em>was</em> us — which slice?</h2>
  <div style="font-size:.64em;max-width:34ch">
    <p><b>Adtributor</b> attributes the internal residual to a dimension as a citable %.</p>
    <div class="card fragment"><p style="margin:0">~70% of the internal drop came from the <b>v2.3 update</b> on <b>mobile · SEA</b>.</p>
      <span class="tag i">Internal</span> <span class="tag n">Possible</span> <span class="cite">E7, E9</span></div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 4: Slide 10 — Layer 4: Dual-axis confidence (matrix SVG)**

```html
<section>
  <p class="microlabel">Layer 4 · Confidence</p>
  <h2>Most tools give one number. We give two.</h2>
  <div class="cols">
    <div style="font-size:.62em"><p>How <b>likely</b> is this cause — and how <b>good</b> is the evidence for it?</p>
      <p class="fragment muted">Plotted on a likelihood × evidence-quality grid, per claim.</p></div>
    <div><!-- PASTE matrix <svg> from Task 3 --></div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 5: Slide 11 — Layer 5: Honesty / abstention**

```html
<section>
  <p class="microlabel">Layer 5 · Honesty</p>
  <h2>When the evidence is thin, it says so.</h2>
  <div class="cols">
    <div class="gaps" style="font-size:.58em"><p class="microlabel">Assumptions &amp; gaps</p>
      <ul style="margin:0;padding-left:1.1em"><li>Pre-period < 14 days → confidence lowered.</li><li>No cohort-level export → segment is indicative.</li></ul></div>
    <div style="font-size:.6em">
      <p class="fragment">The <b>self-consistency gate</b> (N samples must agree) + <b>citation validator</b> reject shaky claims.</p>
      <p class="fragment big" style="font-size:1em">Scenarios, not decisions — the human decides.</p>
    </div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 6: Verify all five layers**

Run: reload; arrow + space through slides 7→11, clicking to trigger each fragment.
Expected: each layer shows method+visual; fragments reveal in order; the overlay's counterfactual gap appears on its fragment click; nothing clips.

- [ ] **Step 7: Commit**

```bash
git add deck/index.html
git commit -m "feat(deck): slides 7-11 (dossier layer-walk with fragments)"
```

---

## Task 8: Slide 12 (Architecture)

**Files:**
- Modify: `deck/index.html` (append one section)
- Modify: `deck/theme/gaa.css` (add `.arch` styles)

- [ ] **Step 1: Add architecture styles**

```css
.arch{ display:flex; flex-direction:column; gap:.5em; font-size:.46em; }
.arch .tier{ display:flex; gap:.5em; align-items:stretch; justify-content:center; }
.arch .box{ background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:.5em .7em; box-shadow:var(--shadow); text-align:center; }
.arch .box.agent{ border-color:var(--blue); }
.arch .ext{ color:var(--muted); font-size:.85em; text-align:center; }
```

- [ ] **Step 2: Append the architecture slide**

```html
<section>
  <p class="eyebrow">How it's built</p>
  <h2>One agent. Deterministic core. LLM at the edges.</h2>
  <div class="arch" style="margin-top:.4em">
    <div class="tier"><div class="box">Browser — Next.js on <b>Vercel</b> · chat · live trace · dossier iframe</div></div>
    <div class="ext">↕ /invocations · /chat (SSE)</div>
    <div class="tier"><div class="box agent"><b>FastAPI Custom Agent</b> on GreenNode AgentBase<br>
      <span class="mono">/chat</span> loop · resumable pipeline <span class="mono">plan→crawl→modules→synth→render</span> · <span class="mono">/runs/&lt;id&gt;</span> dossier</div></div>
    <div class="tier">
      <div class="box">Deterministic engine<br><span class="muted">PELT · STL · Adtributor · BSTS · ledger · citation validator</span></div>
      <div class="box">LLM (Qwen 3.5 27B via MaaS)<br><span class="muted">route · map columns · narrate</span></div>
    </div>
    <div class="ext">External: MaaS LLM · SteamCharts / Roblox trackers · Perplexity sonar (opt-in)</div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 3: Verify**

Run: reload; slide 12.
Expected: a three-tier stack (Browser → Custom Agent → engine+LLM) with the agent tier blue-bordered and external deps as a footnote line; fits the frame.

- [ ] **Step 4: Commit**

```bash
git add deck/index.html deck/theme/gaa.css
git commit -m "feat(deck): slide 12 (architecture)"
```

---

## Task 9: Slides 13–14 (Proof, Close) + QR placeholder

**Files:**
- Modify: `deck/index.html` (append two sections)
- The QR image is generated in Task 10; reference `assets/img/qr.png` now.

- [ ] **Step 1: Append slide 13 (proof)**

```html
<section>
  <p class="eyebrow">Proof</p>
  <h2>Real, not a mockup.</h2>
  <div class="cols">
    <div style="font-size:.6em">
      <p>✓ <b>177 passing tests</b> · TDD throughout</p>
      <p>✓ Engine verified end-to-end with a fake LLM</p>
      <p>✓ Deployed live on <b>GreenNode AgentBase</b> + <b>Vercel</b></p>
      <p>✓ Real Roblox / Steam benchmark crawl</p>
    </div>
    <div class="center">
      <img src="assets/img/qr.png" alt="Open the live app" style="width:160px;height:160px;border-radius:10px;border:1px solid var(--border)" />
      <p class="mono" style="font-size:.42em">game-attribution-agent.vercel.app</p>
    </div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 2: Append slide 14 (close)**

```html
<section class="stack-center center" data-state="title">
  <h2 class="big" style="max-width:28ch">Attribution done honestly — every claim cited, every gap admitted.</h2>
  <p class="muted" style="font-size:.6em;max-width:34ch;text-align:center">Next: multi-game portfolio views · a toolbox that grows (tool promotion) · admin-only hardening.</p>
  <div class="row center" style="gap:1em;margin-top:1em">
    <img src="assets/img/qr.png" alt="" style="width:90px;height:90px;border-radius:8px;border:1px solid var(--border)" />
    <div><p class="microlabel" style="margin:0">Game Attribution Agent</p>
      <p class="mono" style="font-size:.46em;margin:.2em 0 0">game-attribution-agent.vercel.app</p></div>
  </div>
  <aside class="notes"></aside>
</section>
```

- [ ] **Step 3: Verify (QR will be a broken img until Task 10)**

Run: reload; slides 13→14.
Expected: proof checklist and close render correctly; the QR `<img>` is a broken-image placeholder for now (fixed next task).

- [ ] **Step 4: Commit**

```bash
git add deck/index.html
git commit -m "feat(deck): slides 13-14 (proof + close)"
```

---

## Task 10: Generate the QR code

**Files:**
- Create: `deck/assets/img/qr.png`

- [ ] **Step 1: Generate the QR to the live app**

Run:
```bash
cd deck && mkdir -p assets/img
npx --yes qrcode -o assets/img/qr.png "https://game-attribution-agent.vercel.app"
```
Expected: `assets/img/qr.png` created.

- [ ] **Step 2: Verify it scans and renders**

Run: reload slides 13–14; scan the QR with a phone.
Expected: the QR renders crisply in both slides and resolves to the live app.

- [ ] **Step 3: Commit**

```bash
git add deck/assets/img/qr.png
git commit -m "feat(deck): QR code to the live app"
```

---

## Task 11: Capture real screenshots from the live app

**Files:**
- Create: `deck/tools/capture.mjs`
- Create: `deck/assets/screenshots/chat.png` (and `dossier.png` if a clean run is reachable)
- Modify: `deck/index.html` (slides 3–4: use screenshots as primary, keep recreation as fallback note)

The live frontend is up (HTTP 200) but the backend `/health` was flaky — so capture the **chat landing reliably**, and attempt a dossier capture; if the run path is degraded, keep the in-deck recreation for slide 4 and document it.

- [ ] **Step 1: Write the Playwright capture script**

```js
// deck/tools/capture.mjs — run: node tools/capture.mjs
import { chromium } from "playwright";
const URL = "https://game-attribution-agent.vercel.app";
const OUT = new URL("../assets/screenshots/", import.meta.url).pathname;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
await page.goto(URL, { waitUntil: "networkidle" });
await page.screenshot({ path: OUT + "chat.png" });
console.log("captured chat.png");
// Best-effort dossier: type a prompt and wait; tolerate failure (backend may be down)
try {
  const box = page.locator('textarea, [contenteditable="true"]').first();
  await box.click({ timeout: 5000 });
  await box.fill("What's going on with my Roblox game's DAU this week?");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(45000); // allow the pipeline to run
  await page.screenshot({ path: OUT + "dossier.png", fullPage: true });
  console.log("captured dossier.png");
} catch (e) { console.log("dossier capture skipped:", e.message); }
await browser.close();
```

- [ ] **Step 2: Run the capture using the frontend's Playwright**

Run:
```bash
cd deck && mkdir -p assets/screenshots
PLAYWRIGHT_BROWSERS_PATH="$(cd ../frontend && npm root)/.." \
  node --experimental-vm-modules - <<'EOF' 2>/dev/null || \
  ( cd ../frontend && node ../deck/tools/capture.mjs )
EOF
# Simpler path if the above is awkward: run from frontend where playwright + chromium exist:
cd ../frontend && node ../deck/tools/capture.mjs
```
Expected: `deck/assets/screenshots/chat.png` exists. `dossier.png` may or may not (logged "skipped" if the backend was down — that's acceptable).

- [ ] **Step 3: Wire the real chat screenshot into slide 3**

In slide 3, add below the card (keep the existing card as a caption):
```html
<img src="assets/screenshots/chat.png" alt="GAA chat" style="max-height:46vh;border-radius:12px;border:1px solid var(--border);box-shadow:var(--shadow);margin-top:.5em" />
```

- [ ] **Step 4: Slide 4 — use `dossier.png` if it was captured; otherwise keep the recreation**

If `assets/screenshots/dossier.png` exists and looks clean, set slide 4's main visual to it; otherwise leave the Task-5 recreation in place and add a tiny `data-note`. Decide by eye.

- [ ] **Step 5: Verify offline-safety still holds**

Run: turn off wifi, reload `deck/index.html`, view slides 3–4.
Expected: screenshots (now local files) load with no network; nothing depends on the live app at present time.

- [ ] **Step 6: Commit**

```bash
git add deck/tools/capture.mjs deck/assets/screenshots deck/index.html
git commit -m "feat(deck): capture live-app screenshots; wire into demo slides"
```

---

## Task 12: Speaker notes (talk track)

**Files:**
- Modify: `deck/index.html` (fill every `<aside class="notes">`)

Write a 2–4 sentence spoken track per slide into each slide's `<aside class="notes">`. Keep them spoken-voice, not bullet dumps. Example for slide 4:

```html
<aside class="notes">This took one sentence from me. Behind it: it read my export, crawled the genre's player counts, ran four analyses, and wrote a cited dossier. Don't explain the parts yet — let the room feel the speed. Then ask the hard question on the next slide.</aside>
```

- [ ] **Step 1: Fill notes for all 14 slides** (one `<aside>` per `<section>`; content per the talk intent in the spec §4).

- [ ] **Step 2: Verify presenter view**

Run: reload `deck/index.html`, press `S`.
Expected: speaker window opens showing current+next slide and the notes for each slide; notes advance with the deck.

- [ ] **Step 3: Commit**

```bash
git add deck/index.html
git commit -m "feat(deck): speaker notes for all slides"
```

---

## Task 13: PDF export + deck README

**Files:**
- Create: `deck/README.md`
- Create (build artifact, gitignored): `deck/gaa-deck.pdf`

- [ ] **Step 1: Export a PDF**

Run:
```bash
cd deck
npx --yes serve -l 3000 . &   # serve so print-pdf can load assets without file:// quirks
sleep 2
npx --yes decktape reveal "http://localhost:3000/?print-pdf" gaa-deck.pdf
kill %1
ls -la gaa-deck.pdf
```
Expected: `gaa-deck.pdf` with 14 pages. (Fallback if decktape struggles: open `http://localhost:3000/?print-pdf` in Chrome → Print → Save as PDF, Landscape, margins None, Background graphics ON.)

- [ ] **Step 2: Open the PDF and check fidelity**

Expected: all 14 slides present, fonts embedded, colors correct, fragments shown in their final (all-revealed) state, charts crisp.

- [ ] **Step 3: Write `deck/README.md`**

```markdown
# Game Attribution Agent — Pitch Deck

On-brand reveal.js deck. Self-contained and offline-safe.

## Present
- **Double-click `index.html`** (works offline), or `npm run serve` then open http://localhost:3000.
- Arrow keys / space to advance; fragments reveal on click.
- Press **S** for speaker view (current + next slide + notes).
- Press **F** for fullscreen, **ESC** for the slide overview.

## Export to PDF
`npm run pdf` (serves on :3000 and runs decktape → `gaa-deck.pdf`).
Or open `http://localhost:3000/?print-pdf` in Chrome → Print → Save as PDF (Landscape, margins None, Background graphics ON).

## Refresh demo screenshots
From `frontend/` (it has Playwright + chromium): `node ../deck/tools/capture.mjs`.

## Structure
- `index.html` — all 14 slides
- `theme/gaa.css` — brand theme (GAA dossier tokens)
- `assets/` — charts (inline), screenshots, QR
- `vendor/` — reveal.js + Geist fonts (frozen, offline)
```

- [ ] **Step 4: Commit**

```bash
git add deck/README.md
git commit -m "docs(deck): README — present, export, refresh-capture"
```

---

## Task 14: Final end-to-end verification

**Files:** none (verification + final commit if any fixups)

- [ ] **Step 1: Full run-through at presentation size**

Run: `open deck/index.html`, press `F`.
Expected: all **14 slides** advance cleanly at 16:9; every fragment fires in order; no text/visual clips off-frame; blue=internal / amber=market consistent throughout.

- [ ] **Step 2: Offline check**

Run: disable network, reload, run through again.
Expected: fonts, reveal.js, charts, screenshots, QR all load locally — zero network requests (verify in DevTools Network tab).

- [ ] **Step 3: PDF + QR final check**

Expected: `gaa-deck.pdf` matches the live deck; the QR resolves to `https://game-attribution-agent.vercel.app`.

- [ ] **Step 4: Fix anything found, then commit**

```bash
git add -A deck
git commit -m "fix(deck): final verification fixups" --allow-empty
```

- [ ] **Step 5: Report status** — confirm slide count, offline-safety, PDF page count, and QR resolution to the user. Offer to open a PR for `deck/gaa-pitch-deck` → `main`.

---

## Self-Review (against the spec)

**Spec coverage:**
- Visual system (§3) → Task 2 ✓ · Signature visuals (§3, §5) → Task 3 ✓
- 14-slide outline (§4) → Tasks 4–9 (1-2, 3-4, 5-6, 7-11, 12, 13-14) ✓
- reveal.js vendored / offline / `deck/` layout (§5) → Tasks 1, 14 ✓
- Fragments for layer-walk (§5) → Tasks 6, 7 ✓
- Demo captured from live app + offline fallback (§6) → Tasks 5 (recreation), 11 (capture) ✓
- Backend-flaky → recorded/recreation fallback (§6) → Task 11 best-effort + recreation ✓
- QR (§2 extras) → Task 10 ✓ · PDF leave-behind (§2 extras) → Task 13 ✓
- Speaker notes (§5) → Task 12 ✓ · Verification (§7) → Task 14 ✓
- Dark toggle / real-dossier-iframe explicitly **out of scope** (§8) — no tasks, correct ✓

**Placeholder scan:** No "TBD/TODO". The two "paste the SVG from Task 3" references point at concrete code in Task 3 Step 1 (intentional reuse of the same artifact, not a vague placeholder). Slide-4 screenshot-vs-recreation is an explicit by-eye decision, not an unfilled blank.

**Type/name consistency:** CSS class names (`.kicker`, `.microlabel`, `.eyebrow`, `.card`, `.pill`, `.tag.i/.m/.n`, `.cite`, `.cause.i/.m`, `.gaps`, `.chain`, `.arch`, `.cols`, `.stack-center`, `.big`, `.mono`, `.muted`) are defined in Tasks 2/6/8 before use in Tasks 4–9. Asset paths (`assets/img/qr.png`, `assets/screenshots/chat.png`) are consistent between the slide that references them and the task that creates them. Reveal config (1280×720) matches the verification sizes.
