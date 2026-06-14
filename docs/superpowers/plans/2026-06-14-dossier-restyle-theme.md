# Dossier Restyle + Light/Dark Theming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Game Attribution Agent dossier (`report.html`) as app-native cards and make it adapt live to the app's light/dark theme, charts included.

**Architecture:** `report.html` is rendered once and stored as a static file, then embedded in a sandboxed (opaque-origin) iframe beside the chat. So theming must live *inside* the document. The dossier ships a CSS-variable theme system toggled by a `data-theme` attribute and a tiny script that (a) listens for a `gaa-theme` `postMessage` from the parent, (b) announces readiness with `gaa-theme-ready`, and (c) recolors the Plotly charts via `Plotly.relayout`. The parent (`artifacts-pane.tsx`) reads `next-themes`' `resolvedTheme` and posts it on load, on theme change, and in reply to the ready handshake.

**Tech Stack:** Python (Jinja2, Plotly, pydantic), pytest; Next.js / React / TypeScript, `next-themes`.

**Reference spec:** `docs/superpowers/specs/2026-06-14-dossier-restyle-theme-design.md`

**Branch:** `feat/dossier-restyle-theme` (already created; spec already committed).

---

## File Structure

- `src/gaa/core/render/charts.py` — *modify*. Make all three Plotly figures transparent so the dossier card surface shows through and theme controls the colors.
- `src/gaa/core/render/report.py` — *modify*. Give charts stable `div_id`s (the JS relayout targets) and thread `metric`/`start`/`end` into the template for the header label.
- `src/gaa/core/render/templates/report.html.j2` — *replace*. Direction-B card layout + CSS-variable theme system + inline theme/handshake/chart-relayout script. **Primary change.**
- `frontend/components/gaa/artifacts-pane.tsx` — *modify*. `postMessage` theme wiring via `next-themes`.
- `tests/render/test_charts.py` — *modify*. Assert transparent backgrounds.
- `tests/render/test_report.py` — *modify*. Assert stable chart ids + theme contract markers.

Run all backend tests with: `pytest tests/render -q`

---

### Task 1: Transparent Plotly chart backgrounds

**Files:**
- Modify: `src/gaa/core/render/charts.py`
- Test: `tests/render/test_charts.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/render/test_charts.py` (the imports `pandas as pd`, `timeseries_fig, overlay_fig, confidence_matrix_fig`, `AttributionHypothesis, Cause, Causes`, `Confidence` already exist at the top of the file):

```python
def test_charts_have_transparent_backgrounds():
    s = pd.Series([100.0, 90.0, 60.0],
                  index=pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]))
    genre = {"2026-05-01": 100.0, "2026-05-03": 98.0}
    h = AttributionHypothesis(
        main_story="x", confidence=Confidence(likelihood="Likely", evidence_quality="Moderate"),
        causes=Causes(internal=[Cause(claim="a", evidence_ids=["L1"], likelihood="Likely",
                                       evidence_quality="Strong")]))
    figs = [timeseries_fig(s, "dau", "2026-05-01", "2026-05-03"),
            overlay_fig(s, genre, "dau"),
            confidence_matrix_fig(h)]
    for fig in figs:
        assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
        assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/render/test_charts.py::test_charts_have_transparent_backgrounds -v`
Expected: FAIL — `paper_bgcolor` is `None` (not set), assertion fails.

- [ ] **Step 3: Add transparent backgrounds to each figure**

In `src/gaa/core/render/charts.py`, add the two kwargs to each `fig.update_layout(...)` call. The three call sites become:

`timeseries_fig`:
```python
    fig.update_layout(title=f"{metric} over time", template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
```

`overlay_fig`:
```python
    fig.update_layout(title="You vs the market (indexed to 100)", template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
```

`confidence_matrix_fig` (append the two kwargs to the existing `fig.update_layout(...)` — keep all current `xaxis`/`yaxis` args):
```python
    fig.update_layout(title="Confidence matrix (likelihood × evidence)",
                      xaxis={"tickvals": [1, 2, 3], "ticktext": ["Weak", "Moderate", "Strong"],
                             "title": "Evidence quality", "range": [0.5, 3.5]},
                      yaxis={"tickvals": [1, 2, 3, 4],
                             "ticktext": ["Unlikely", "Possible", "Likely", "Very likely"],
                             "title": "Likelihood", "range": [0.5, 4.5]},
                      template="plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/render/test_charts.py -v`
Expected: PASS (the new test + the three existing chart tests).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/render/charts.py tests/render/test_charts.py
git commit -m "feat(render): transparent Plotly backgrounds so the dossier controls chart surface"
```

---

### Task 2: Stable chart div ids + thread metric/start/end into the template

**Files:**
- Modify: `src/gaa/core/render/report.py`
- Test: `tests/render/test_report.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/render/test_report.py` (imports and the `_hyp()` helper already exist at the top):

```python
def test_report_charts_have_stable_ids():
    series = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    html = render_report(_hyp(), metric="dau", start="2026-05-01", end="2026-05-03",
                         series=series, genre_trend={"2026-05-01": 100.0, "2026-05-03": 98.0})
    assert "gaa-chart-timeseries" in html
    assert "gaa-chart-overlay" in html
    assert "gaa-chart-matrix" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/render/test_report.py::test_report_charts_have_stable_ids -v`
Expected: FAIL — current chart divs use random UUID ids, so these strings are absent.

- [ ] **Step 3: Add div_id to `_div` and pass stable ids + render args**

Replace the body of `src/gaa/core/render/report.py` from `def _div` to the end of `render_report` with:

```python
def _div(fig, div_id: str) -> str:
    return pio.to_html(fig, include_plotlyjs=False, full_html=False, div_id=div_id,
                       default_width="100%", default_height="380px")


def render_report(h: AttributionHypothesis, metric: str, start: str, end: str,
                  series: pd.Series, genre_trend: dict) -> str:
    charts = {
        "timeseries": _div(timeseries_fig(series, metric, start, end), "gaa-chart-timeseries"),
        "overlay": _div(overlay_fig(series, genre_trend, metric), "gaa-chart-overlay"),
        "matrix": _div(confidence_matrix_fig(h), "gaa-chart-matrix"),
    }
    return _env.get_template("report.html.j2").render(
        h=h, charts=charts, plotlyjs=pyo.get_plotlyjs(),
        metric=metric, start=start, end=end)
```

(The new `metric`/`start`/`end` template variables are harmless to the current template — Jinja ignores unused kwargs — and are consumed by the template in Task 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/render/test_report.py -v`
Expected: PASS (new test + the existing `test_report_is_self_contained_html`).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/render/report.py tests/render/test_report.py
git commit -m "feat(render): stable chart div ids + thread metric/start/end into template"
```

---

### Task 3: Restyle the template as app-native cards with a light/dark theme system

**Files:**
- Replace: `src/gaa/core/render/templates/report.html.j2`
- Test: `tests/render/test_report.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/render/test_report.py`:

```python
def test_report_supports_light_dark_theme():
    series = pd.Series([100.0, 60.0], index=pd.to_datetime(["2026-05-01", "2026-05-03"]))
    html = render_report(_hyp(), metric="dau", start="2026-05-01", end="2026-05-03",
                         series=series, genre_trend={"2026-05-01": 100.0, "2026-05-03": 98.0})
    assert "data-theme" in html                 # themed document root
    assert '[data-theme="dark"]' in html        # dark-mode token block
    assert "gaa-theme" in html                  # parent -> iframe message type
    assert "gaa-theme-ready" in html            # iframe -> parent handshake
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/render/test_report.py::test_report_supports_light_dark_theme -v`
Expected: FAIL — the current template has none of these markers.

- [ ] **Step 3: Replace the template**

Overwrite `src/gaa/core/render/templates/report.html.j2` with exactly this content:

```jinja
<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ h.main_story }}</title>
<script>{{ plotlyjs|safe }}</script>
<style>
 :root{
   --bg:oklch(0.985 0 0); --fg:oklch(0.12 0 0); --card:oklch(1 0 0);
   --muted:oklch(0.94 0 0); --mfg:oklch(0.58 0 0); --border:oklch(0.9 0 0);
   --secondary:oklch(0.965 0 0);
   --blue:#2563eb; --blue-bg:#eff6ff; --blue-bd:#dbeafe;
   --amber:#b45309; --amber-ln:#d97706; --amber-bg:#fffbeb; --amber-bd:#fde68a;
   --warn-bg:#fffbeb; --warn-bd:#fde68a; --warn-fg:#92400e;
   --shadow:0 1px 2px rgba(0,0,0,.05);
 }
 html[data-theme="dark"]{
   --bg:oklch(0.195 0 0); --fg:oklch(0.94 0 0); --card:oklch(0.225 0 0);
   --muted:oklch(0.165 0 0); --mfg:oklch(0.6 0 0); --border:oklch(0.27 0 0);
   --secondary:oklch(0.26 0 0);
   --blue:#60a5fa; --blue-bg:rgba(96,165,250,.13); --blue-bd:rgba(96,165,250,.32);
   --amber:#fbbf24; --amber-ln:#f59e0b; --amber-bg:rgba(251,191,36,.12); --amber-bd:rgba(251,191,36,.3);
   --warn-bg:rgba(251,191,36,.1); --warn-bd:rgba(251,191,36,.28); --warn-fg:#fcd34d;
   --shadow:0 1px 2px rgba(0,0,0,.3);
 }
 *{box-sizing:border-box}
 body{margin:0;padding:20px;background:var(--bg);color:var(--fg);
   font-family:"Geist",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
   font-size:13.5px;line-height:1.55;-webkit-font-smoothing:antialiased}
 .wrap{max-width:880px;margin:0 auto}
 .card{background:var(--card);border:1px solid var(--border);border-radius:12px;
   padding:16px 18px;margin-bottom:12px;box-shadow:var(--shadow)}
 .lbl{font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--mfg);
   font-weight:600;margin-bottom:9px}
 .headline{font-size:19px;line-height:1.34;font-weight:600;letter-spacing:-0.012em;margin:0}
 .conf{display:inline-flex;align-items:center;gap:7px;margin-top:13px;font-size:11.5px;
   font-weight:500;padding:4px 11px;background:var(--secondary);border:1px solid var(--border);
   border-radius:8px;color:var(--fg)}
 .conf .dot{width:7px;height:7px;border-radius:50%;background:var(--blue)}
 .cause{border-left:3px solid;padding:9px 0 9px 13px;margin:11px 0}
 .cause:first-of-type{margin-top:0}
 .cause.i{border-color:var(--blue)} .cause.m{border-color:var(--amber-ln)}
 .cause p{margin:0}
 .meta{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
 .tag{display:inline-block;font-size:10px;font-weight:600;padding:2px 9px;border-radius:6px;letter-spacing:.02em}
 .tag.i{background:var(--blue-bg);color:var(--blue);border:1px solid var(--blue-bd)}
 .tag.m{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-bd)}
 .tag.n{background:var(--muted);color:var(--mfg);border:1px solid var(--border)}
 .cite{font-family:ui-monospace,"Geist Mono",monospace;font-size:10px;color:var(--mfg);
   background:var(--muted);padding:2px 7px;border-radius:5px}
 .scen,.risk{display:flex;gap:9px;margin:9px 0;align-items:baseline}
 .scen:first-of-type,.risk:first-of-type{margin-top:0}
 .mk{flex:none;color:var(--mfg);font-size:12px;transform:translateY(1px)}
 .watch{display:block;margin-top:4px;font-family:ui-monospace,monospace;font-size:10px;color:var(--mfg)}
 .gaps{background:var(--warn-bg);border:1px solid var(--warn-bd);border-radius:12px;
   padding:14px 18px;margin-bottom:12px}
 .gaps .lbl{color:var(--warn-fg)}
 .gaps ul{margin:0;padding-left:18px} .gaps li{margin:3px 0}
 .ev{font-size:12px;color:var(--mfg);margin:6px 0}
 .ev b{color:var(--fg);font-family:ui-monospace,monospace;font-weight:600}
 .ev .src{font-size:10px;text-transform:uppercase;letter-spacing:.05em;background:var(--muted);
   border:1px solid var(--border);border-radius:5px;padding:1px 6px;margin:0 6px}
 .foot{font-size:11px;color:var(--mfg);text-align:center;margin-top:4px}
</style></head>
<body>
<div class="wrap">

 <div class="card">
   <div class="lbl">Attribution dossier · {{ metric }} · {{ start }} – {{ end }}</div>
   <p class="headline">{{ h.main_story }}</p>
   <span class="conf"><span class="dot"></span>{{ h.confidence.likelihood }} · {{ h.confidence.evidence_quality }} evidence</span>
 </div>

 <div class="card">{{ charts.timeseries|safe }}</div>
 <div class="card">{{ charts.overlay|safe }}</div>

 <div class="card">
   <div class="lbl">Causes</div>
   {% for c in h.causes.internal %}
   <div class="cause i"><p>{{ c.claim }}</p>
     <div class="meta"><span class="tag i">Internal</span><span class="tag n">{{ c.likelihood }}</span>
       <span class="tag n">{{ c.evidence_quality }} evidence</span><span class="cite">{{ c.evidence_ids|join(', ') }}</span></div>
   </div>{% endfor %}
   {% for c in h.causes.market %}
   <div class="cause m"><p>{{ c.claim }}</p>
     <div class="meta"><span class="tag m">Market</span><span class="tag n">{{ c.likelihood }}</span>
       <span class="tag n">{{ c.evidence_quality }} evidence</span><span class="cite">{{ c.evidence_ids|join(', ') }}</span></div>
   </div>{% endfor %}
 </div>

 <div class="card">{{ charts.matrix|safe }}</div>

 {% if h.scenarios %}
 <div class="card">
   <div class="lbl">Next scenarios</div>
   {% for s in h.scenarios %}
   <div class="scen"><span class="mk">→</span><div><p>{{ s.description }}</p>
     {% if s.signals_to_watch %}<span class="watch">watch: {{ s.signals_to_watch|join('; ') }}</span>{% endif %}
     <div class="meta"><span class="tag n">{{ s.likelihood }}</span><span class="tag n">{{ s.evidence_quality }} evidence</span></div>
   </div></div>{% endfor %}
 </div>{% endif %}

 {% if h.risks %}
 <div class="card">
   <div class="lbl">Risks</div>
   {% for r in h.risks %}
   <div class="risk"><span class="mk">⚠</span><div><p>{{ r.description }}</p>
     <div class="meta"><span class="tag n">{{ r.likelihood }}</span><span class="tag n">{{ r.evidence_quality }} evidence</span></div>
   </div></div>{% endfor %}
 </div>{% endif %}

 {% if h.assumptions_and_gaps %}
 <div class="gaps"><div class="lbl">Assumptions &amp; gaps</div>
   <ul>{% for g in h.assumptions_and_gaps %}<li>{{ g }}</li>{% endfor %}</ul>
 </div>{% endif %}

 {% if h.evidence %}
 <div class="card">
   <div class="lbl">Evidence</div>
   {% for e in h.evidence %}<div class="ev"><b>{{ e.id }}</b><span class="src">{{ e.source_type }}/{{ e.strength }}</span>{{ e.claim }} ({{ e.value }}) — {{ e.source }}</div>{% endfor %}
 </div>{% endif %}

 <p class="foot">Generated by an AI agent. Scenarios, not decisions — the human decides.</p>

</div>

<script>
 var CHART_IDS = ["gaa-chart-timeseries", "gaa-chart-overlay", "gaa-chart-matrix"];
 var PATCH = {
   light: {paper_bgcolor:"rgba(0,0,0,0)", plot_bgcolor:"rgba(0,0,0,0)", "font.color":"#1f1f1f",
     "xaxis.gridcolor":"#e7e5e4", "yaxis.gridcolor":"#e7e5e4", "xaxis.color":"#8a8a8a", "yaxis.color":"#8a8a8a",
     "xaxis.linecolor":"#e3e3e3", "yaxis.linecolor":"#e3e3e3",
     "xaxis.zerolinecolor":"#e7e5e4", "yaxis.zerolinecolor":"#e7e5e4", "legend.font.color":"#57534e"},
   dark: {paper_bgcolor:"rgba(0,0,0,0)", plot_bgcolor:"rgba(0,0,0,0)", "font.color":"#ededed",
     "xaxis.gridcolor":"#3d3d3d", "yaxis.gridcolor":"#3d3d3d", "xaxis.color":"#919191", "yaxis.color":"#919191",
     "xaxis.linecolor":"#3d3d3d", "yaxis.linecolor":"#3d3d3d",
     "xaxis.zerolinecolor":"#3d3d3d", "yaxis.zerolinecolor":"#3d3d3d", "legend.font.color":"#a0a0a0"}
 };
 function applyChartTheme(t, tries) {
   tries = tries || 0;
   var ready = window.Plotly && CHART_IDS.every(function(id) {
     var el = document.getElementById(id); return !el || el.data;
   });
   if (!ready && tries < 40) { setTimeout(function(){ applyChartTheme(t, tries + 1); }, 100); return; }
   CHART_IDS.forEach(function(id) {
     var el = document.getElementById(id);
     if (el && el.data) { try { window.Plotly.relayout(el, PATCH[t]); } catch (e) {} }
   });
 }
 function applyTheme(t) {
   if (t !== "dark" && t !== "light") t = "light";
   document.documentElement.setAttribute("data-theme", t);
   applyChartTheme(t);
 }
 window.addEventListener("message", function(e) {
   var d = e.data;
   if (d && d.type === "gaa-theme") { applyTheme(d.theme); }
 });
 applyTheme("light");
 try { parent.postMessage({ type: "gaa-theme-ready" }, "*"); } catch (e) {}
</script>
</body></html>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/render -q`
Expected: PASS — the new theme test, the stable-ids test, the transparent-bg test, and the existing `test_report_is_self_contained_html` (which still finds `main_story`, the `Confidence matrix` Plotly title, `no UA data`, and `Plotly`).

- [ ] **Step 5: Eyeball the rendered HTML (light)**

Render a sample and open it:

```bash
python -c "
import pandas as pd
from gaa.core.render.report import render_report
from gaa.core.schema.hypothesis import AttributionHypothesis, Cause, Causes, Scenario, Risk
from gaa.core.schema.confidence import Confidence
from gaa.core.schema.ledger import LedgerEntry
h = AttributionHypothesis(
    main_story='DAU fell 23% after the June 3 update — most likely a rival\'s TikTok-fueled launch, not the update.',
    confidence=Confidence(likelihood='Likely', evidence_quality='Moderate'),
    causes=Causes(
        internal=[Cause(claim='June 3 update raised crashes 1.8x on low-end Android.', evidence_ids=['L2','L5'], likelihood='Possible', evidence_quality='Moderate')],
        market=[Cause(claim='Rival Sky Saga launch pulled creators; +140% TikTok mentions.', evidence_ids=['L7','L9'], likelihood='Likely', evidence_quality='Strong')]),
    scenarios=[Scenario(description='If creator interest cools, DAU partially recovers in 3-4 weeks.', likelihood='Possible', evidence_quality='Moderate', signals_to_watch=['TikTok mention volume','Sky Saga store rank'])],
    risks=[Risk(description='Blaming the rival could mask a real retention bug.', likelihood='Possible', evidence_quality='Moderate')],
    evidence=[LedgerEntry(id='L7', module='social', claim='Genre TikTok mentions +140%', value='3.2M->7.7M', source='Social Signal Provider', source_type='external', strength='high')],
    assumptions_and_gaps=['Genre index proxied from 6 titles.'])
s = pd.Series([100.0,98.0,60.0], index=pd.to_datetime(['2026-05-20','2026-06-03','2026-06-14']))
open('/tmp/dossier-sample.html','w').write(render_report(h, 'DAU', '2026-05-20', '2026-06-14', s, {'2026-05-20':100.0,'2026-06-14':94.0}))
print('wrote /tmp/dossier-sample.html')
"
open /tmp/dossier-sample.html
```

Expected: the card-based Direction-B dossier in **light** theme — headline card, two chart cards, a Causes card with blue (internal) / amber (market) rails and tags, a confidence-matrix card, scenarios, risks, a tinted gaps panel, and an evidence row. (Dark theme + chart recolor is driven by the parent and is verified end-to-end in Task 5.)

- [ ] **Step 6: Commit**

```bash
git add src/gaa/core/render/templates/report.html.j2 tests/render/test_report.py
git commit -m "feat(render): app-native card dossier + light/dark theme system + chart relayout"
```

---

### Task 4: Wire the parent to push the theme into the dossier iframe

**Files:**
- Modify: `frontend/components/gaa/artifacts-pane.tsx`

There is no JS unit-test runner in this repo, so this task is verified by typecheck/lint + manual end-to-end (Task 5).

- [ ] **Step 1: Update the React import**

In `frontend/components/gaa/artifacts-pane.tsx`, replace:

```tsx
import { useState } from "react";
```

with:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
```

- [ ] **Step 2: Add theme state, an iframe ref, and the post helper**

Immediately after the existing two `useState` lines inside the component:

```tsx
  const [sel, setSel] = useState<string | null>(null);
  const [tab, setTab] = useState<"dossier" | "trace">("dossier");
```

add:

```tsx
  const { resolvedTheme } = useTheme();
  const dossierRef = useRef<HTMLIFrameElement>(null);

  // Push the app's current theme into the sandboxed dossier iframe.
  const postTheme = useCallback(() => {
    dossierRef.current?.contentWindow?.postMessage(
      { type: "gaa-theme", theme: resolvedTheme === "dark" ? "dark" : "light" },
      "*"
    );
  }, [resolvedTheme]);

  // Re-post on theme change (and on mount).
  useEffect(() => {
    postTheme();
  }, [postTheme]);

  // Reply to the dossier's ready handshake (covers iframe-loads-first races).
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (
        e.source === dossierRef.current?.contentWindow &&
        e.data?.type === "gaa-theme-ready"
      ) {
        postTheme();
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [postTheme]);
```

- [ ] **Step 3: Attach the ref + onLoad to the dossier iframe**

Replace the dossier `<iframe>` (the one in the `tab === "dossier"` branch) with:

```tsx
        <iframe
          key={runId}
          ref={dossierRef}
          title="dossier"
          sandbox="allow-scripts"
          src={`/api/runs/${encodeURIComponent(runId)}/report.html`}
          onLoad={() => postTheme()}
          className="flex-1 w-full border-0 bg-background"
        />
```

(Leave the `trace` iframe unchanged — it serves raw markdown and is out of scope.)

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && npm run check`
Expected: no new errors from `artifacts-pane.tsx`. (If `npm run check` surfaces only pre-existing repo-wide warnings unrelated to this file, that is acceptable — confirm none reference `artifacts-pane.tsx`.)

- [ ] **Step 5: Commit**

```bash
git add frontend/components/gaa/artifacts-pane.tsx
git commit -m "feat(frontend): post app light/dark theme into the dossier iframe"
```

---

### Task 5: End-to-end verification in the running app

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest tests/render -q`
Expected: all render tests pass.

- [ ] **Step 2: Start the app**

Start the backend (the FastAPI server that serves `/runs/<id>/report.html`) per the project's usual dev workflow, then:

```bash
cd frontend && npm run dev
```

Open the app, select (or run) an analysis so a dossier appears in the right-hand pane.

- [ ] **Step 3: Verify styling + light/dark adaptation**

Confirm, with evidence:
- The dossier renders as **app-native cards** (matches the approved Direction-B mockup) and visually matches the app shell in the **current** theme.
- Toggling the app theme (light ⇄ dark) flips the dossier **with no reload/flash**, and the **Plotly charts recolor** (transparent background, themed fonts/gridlines/axes) — not just the surrounding cards.
- Switching runs (the run selector / `key={runId}` remount) keeps the dossier on the correct theme.
- The browser console shows no errors from the dossier or `artifacts-pane`.

- [ ] **Step 4: Final cleanup commit (if any tweaks were needed)**

If Step 3 required color/spacing tweaks to `report.html.j2` or `artifacts-pane.tsx`, commit them:

```bash
git add -A
git commit -m "fix(dossier): theme/styling polish from end-to-end verification"
```

---

## Self-Review

**1. Spec coverage**

| Spec requirement | Task |
|---|---|
| Restyle as Direction-B app-native cards | Task 3 (template) |
| Exact app OKLCH neutral tokens + blue/amber accents | Task 3 (`:root` / `[data-theme="dark"]`) |
| Theme via `postMessage` (`gaa-theme`) + `gaa-theme-ready` handshake | Task 3 (dossier listener) + Task 4 (parent) |
| Validate by `event.source` (origin is `null` for sandboxed frame) | Task 4 (`e.source === ...contentWindow`) |
| Fully themed charts (transparent bg + JS relayout of fonts/grid/axes) | Task 1 (transparent bg) + Task 3 (`applyChartTheme` / `PATCH`) |
| Stable chart `div_id`s as relayout targets | Task 2 |
| Message-before-charts-ready guard / retry | Task 3 (`applyChartTheme` retry loop) |
| Either-side-mounts-first handshake | Task 3 (ready post) + Task 4 (onLoad + ready reply + theme effect) |
| Iframe remount on run switch re-themes | Task 4 (`key={runId}` + onLoad) — checked in Task 5 Step 3 |
| No-JS graceful default to light | Task 3 (`applyTheme("light")`) |
| Trace tab out of scope | Task 4 (left unchanged) |
| No schema/content/pipeline changes | Tasks render-only; same Jinja fields |
| Tests: stable ids, transparent bg, theme markers, no content regression | Tasks 1–3 |

No gaps.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". Every code step contains complete content.

**3. Type/name consistency:** Chart ids `gaa-chart-timeseries` / `gaa-chart-overlay` / `gaa-chart-matrix` are identical in `report.py` (Task 2), the test (Task 2), and the dossier's `CHART_IDS` (Task 3). Message types `gaa-theme` / `gaa-theme-ready` match between the dossier script (Task 3) and the parent (Task 4). `postTheme` / `dossierRef` / `resolvedTheme` are consistent throughout Task 4. `_div(fig, div_id)` signature matches its three call sites.
