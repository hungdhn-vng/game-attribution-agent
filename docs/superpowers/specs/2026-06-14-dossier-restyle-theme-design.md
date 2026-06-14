# Dossier restyle + light/dark theming — Design

**Date:** 2026-06-14
**Status:** Approved (look + approach), pending spec review
**Topic:** Restyle the Game Attribution Agent dossier (`report.html`) as app-native cards and make it adapt to the app's light/dark theme.

## Goal

The dossier is the agent's headline deliverable: a self-contained HTML report explaining why a game metric moved. It is served per-run and embedded in an iframe beside the chat panel. Today it is minimally styled (system-ui, two accent colors, plain pill badges) and is always light — jarring next to the app's dark theme.

Two outcomes:
1. **Restyle** the dossier as **app-native cards** (Direction B) so it reads as one product with the shadcn chat UI beside it.
2. **Theme adaptation** — the dossier renders light or dark to exactly match the app's current theme, charts included.

Both were validated visually in brainstorming (full-dossier mockup with a working light/dark toggle, approved).

## Context — how the dossier is built and served

- **Rendered once, stored static.** `pipeline.py:273` calls `render_report(...)`; `store.py:73` writes the returned HTML to `report.html` on disk. The backend serves it as a static `FileResponse` (`app.py:113-128`); the Next.js route (`frontend/app/api/runs/[id]/[artifact]/route.ts`) proxies the bytes. **There is no on-demand re-render**, so theming cannot be done server-side per request — it must live inside the document (client-side).
- **Embedded sandboxed.** `frontend/components/gaa/artifacts-pane.tsx` renders `<iframe sandbox="allow-scripts" src="/api/runs/<id>/report.html">`. `allow-scripts` without `allow-same-origin` ⇒ the iframe is an opaque origin: it **cannot** read the parent DOM, `localStorage`, or the `.dark` class. `postMessage` still works across this boundary.
- **App theme.** `next-themes`, `attribute="class"`, `defaultTheme="system"` ⇒ dark mode is a `.dark` class on `<html>`. The source of truth is the in-app (possibly manual) toggle, which is why OS-only `prefers-color-scheme` was rejected.
- **Charts.** `charts.py` builds three Plotly figures (timeseries, you-vs-market overlay, confidence matrix) with `template="plotly_white"` baked in. `report.py` embeds them via `pio.to_html(fig, include_plotlyjs=False, full_html=False)`; `plotly.js` is inlined once in `<head>`.

## Approach (decided)

| Decision | Choice | Why |
|---|---|---|
| Visual direction | **B — app-native cards** | Lives next to the shadcn UI; matching it is the cleanest "intentional" look. Subsumes typography/spacing wins. |
| Theme transport | **Live via `postMessage`** | Static doc in an opaque-origin iframe can't read parent theme. postMessage is the only live channel; mirrors the in-app toggle exactly, no reload/flash. |
| Charts in dark | **Fully themed** | Honors "adapt to the overall theme"; transparent Plotly background + JS recolor of fonts/grid/axes. |

## Architecture

Four edits across two layers. The theme protocol is the contract between them.

### 1. Theme protocol (the contract)

Parent → iframe message:
```js
{ type: "gaa-theme", theme: "light" | "dark" }
```
Iframe → parent, once its listener is registered:
```js
{ type: "gaa-theme-ready" }
```

Handshake (robust to either side loading first):
- **Parent** posts the current theme (a) when it receives `gaa-theme-ready`, (b) on the iframe's `load` event, and (c) whenever the resolved theme changes. Posting more than once is idempotent.
- **Iframe** posts `gaa-theme-ready` as soon as its inline listener is attached (top of `<body>`), and also applies a sensible default (`light`) immediately so it never renders unstyled.

Validation:
- Iframe accepts a message only if `event.data?.type === "gaa-theme"` and `theme ∈ {light,dark}`. Origin is not asserted (theme is non-sensitive; the payload is shape-validated).
- Parent accepts `gaa-theme-ready` only if `event.source === <the dossier iframe's contentWindow>` (origin is `"null"` for the sandboxed frame, so validate by source, not origin).

### 2. Dossier template — `src/gaa/core/render/templates/report.html.j2` (the big change)

- Replace the current `<style>` with a **CSS-variable theme system**: tokens on `:root` (light) overridden under `[data-theme="dark"]`, applied to `document.documentElement`.
  - **Neutrals = exact app tokens** (from `globals.css`):
    - Light: `--bg oklch(0.985 0 0)`, `--fg oklch(0.12 0 0)`, `--card oklch(1 0 0)`, `--muted oklch(0.94 0 0)`, `--mfg oklch(0.58 0 0)`, `--border oklch(0.9 0 0)`, `--secondary oklch(0.965 0 0)`.
    - Dark: `--bg oklch(0.195 0 0)`, `--fg oklch(0.94 0 0)`, `--card oklch(0.225 0 0)`, `--muted oklch(0.165 0 0)`, `--mfg oklch(0.6 0 0)`, `--border oklch(0.27 0 0)`, `--secondary oklch(0.26 0 0)`.
  - **Semantic accents** (only non-neutral color), tuned per theme:
    - Internal (blue): `--blue #2563eb` light / `#60a5fa` dark, with tonal badge bg/border.
    - Market (amber): `--amber #b45309` light / `#fbbf24` dark, with tonal badge bg/border.
  - **Chart vars** for relayout: `--grid oklch(0.92 0 0)` light / `oklch(0.3 0 0)` dark.
- **Layout = Direction B** (matches the approved mockup): carded sections (`--card` bg, `--border`, radius 12px, subtle shadow); section labels as small uppercase muted text; headline + confidence pill; one card per chart; causes with blue/amber left-accent rails + `Internal`/`Market` tonal tags + neutral `likelihood`/`evidence` tags + mono citation chips; scenarios; risks; tinted assumptions-&-gaps panel; evidence list with mono IDs and `source/strength` chips; footer disclaimer. Same Jinja loops/fields as today — **no schema changes**.
- **Font:** `"Geist", ui-sans-serif, system-ui, …` and `ui-monospace, "Geist Mono", monospace`. Geist is referenced by name (matches the app if available) but the document does **not** depend on loading a webfont — the system stack is the reliable fallback. No network dependency added.
- **Inline theme script:**
  - `applyTheme(t)` → sets `documentElement.dataset.theme = t` (CSS handles the rest) and calls `applyChartTheme(t)`.
  - `applyChartTheme(t)` → for each chart div id, if `window.Plotly` and the div exist, `Plotly.relayout(id, patch)` where the patch sets `paper_bgcolor`/`plot_bgcolor` to `"rgba(0,0,0,0)"`, and `font.color` / `xaxis.gridcolor` / `yaxis.gridcolor` / `xaxis.color` / `yaxis.color` / `legend.font.color` to the resolved light or dark values. Guard with a short retry (chart init runs on load) so a theme message arriving before Plotly is ready still applies once ready.
  - `message` listener applies validated `gaa-theme` payloads; posts `gaa-theme-ready` on attach; applies `light` as immediate default.

### 3. Charts — `src/gaa/core/render/charts.py`

- Set `paper_bgcolor="rgba(0,0,0,0)"` and `plot_bgcolor="rgba(0,0,0,0)"` on all three figures so the card background shows through and the dossier controls surface color.
- Keep `template="plotly_white"` as the structural base (margins/spacing) — its white fills are overridden by the transparent backgrounds; fonts/grid/axis colors are driven by the relayout patch at runtime. (No need to switch templates per theme.)
- Trace colors (default blue marker, amber overlay line) read acceptably on both themes; left as-is. The red update-window `vrect` at opacity 0.08 also reads on both.

### 4. Renderer — `src/gaa/core/render/report.py`

- Pass **stable `div_id`s** to `pio.to_html(...)`: `gaa-chart-timeseries`, `gaa-chart-overlay`, `gaa-chart-matrix`. These ids are the contract the template's `applyChartTheme` relayouts against (today the ids are random UUIDs, so JS can't target them).

### 5. Frontend wiring — `frontend/components/gaa/artifacts-pane.tsx`

- `import { useTheme } from "next-themes"`; read `resolvedTheme` (resolves `"system"` → `light|dark`).
- Add a `ref` to the dossier iframe.
- `postTheme()` → `iframeRef.current?.contentWindow?.postMessage({type:"gaa-theme", theme: resolvedTheme === "dark" ? "dark" : "light"}, "*")`.
- `useEffect` on `resolvedTheme` → `postTheme()` (live updates on toggle).
- iframe `onLoad={postTheme}` (covers the load-after-mount case).
- A `message` listener (mounted once) that calls `postTheme()` when it sees `gaa-theme-ready` from the dossier iframe's `contentWindow`.
- Only the **dossier** iframe is themed; the **trace** iframe serves raw `summary.md` as `text/markdown` (browser shows plain text) — out of scope.

## Data flow (theme change)

```
user toggles theme in app
  → next-themes updates resolvedTheme + .dark class
  → artifacts-pane effect fires → postMessage({gaa-theme, dark}) → dossier iframe
  → dossier message listener → applyTheme("dark")
       → documentElement[data-theme]="dark"  (CSS vars switch: bg/card/text/badges)
       → applyChartTheme("dark") → Plotly.relayout(each chart, dark patch)
  → dossier + charts now match the app, no reload
```

## Edge cases & error handling

- **Message before charts ready:** `applyChartTheme` guards on `window.Plotly` + div presence and retries briefly; CSS theme applies instantly regardless.
- **Either side mounts first:** the three-way handshake (ready event + onLoad + theme-change effect) guarantees at least one successful post.
- **Iframe remounts on run switch** (`key={runId}`): new document re-announces `gaa-theme-ready`; parent re-posts. No stale state.
- **No-JS / message never arrives:** dossier defaults to `light` and is fully readable — graceful degradation.
- **Sandbox:** all of the above works under `sandbox="allow-scripts"`; no `allow-same-origin` needed. (No change to the sandbox attribute.)

## Testing

Backend (`tests/render/test_report.py`, extend):
- Rendered HTML contains the three **stable chart div ids**.
- Charts are rendered with **transparent** `paper_bgcolor`/`plot_bgcolor`.
- Template includes the **theme listener** (`gaa-theme` handling) and posts `gaa-theme-ready`.
- CSS defines both `:root` light tokens and `[data-theme="dark"]` overrides.
- Existing content assertions (headline, causes, evidence, disclaimer) still pass — no schema/content regressions.

Frontend:
- The wiring is small and hard to unit-test in isolation (postMessage across an iframe). Verify manually in the running app: load a run, toggle the theme, confirm the dossier + charts flip with no reload and match the shell. (If a lightweight component test exists for artifacts-pane, assert the `onLoad`/effect post the expected payload to a mocked `contentWindow`.)

## Out of scope

- The **trace** tab (raw markdown) styling.
- Bundling/serving the **Geist webfont** inside the iframe (system stack is the intended fallback; can be revisited).
- Any change to the dossier's **content, schema, or pipeline** — this is presentation only.
- Query-param and OS-only theming mechanisms (considered, rejected above).

## Files touched

- `src/gaa/core/render/templates/report.html.j2` — full restyle + theme system + inline theme/handshake/chart-relayout script (primary change).
- `src/gaa/core/render/charts.py` — transparent backgrounds on all three figures.
- `src/gaa/core/render/report.py` — stable `div_id`s for the three charts.
- `frontend/components/gaa/artifacts-pane.tsx` — `postMessage` theme wiring + ready handshake.
- `tests/render/test_report.py` — extend assertions.
