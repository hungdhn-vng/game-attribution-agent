# Frontend E2E — verified against the live agent (2026-06-14)

Ran `pnpm dev` (Next 16 / Turbopack) with `.env.local` pointed at the live runtime
`gaa-custom-agent` v4, and exercised the full proxy→backend chain via curl:

- **/api/chat** (no cookie) → SSE: `thinking`×3 (orchestration×2 + synthesis×1), `activity`×1,
  `token`×6, `done` with a real run_id. Reasoning reveal flows through the proxy.
- **/api/runs/<id>/report.html** → HTTP 200, ~4.58 MB self-contained Plotly dossier (same-origin;
  loads in the sandboxed iframe).
- **/api/upload** (multipart CSV) → `{status:success, mapping, csv_b64}` (onboard_propose).
- **Admin gating**: `exec` without the cookie → "requires admin context"; `/api/admin/unlock`
  with the correct passphrase → 200 + signed httpOnly cookie; `exec` with the cookie → success.

Unit suite: 12/12 (vitest, tests/gaa/*). `pnpm build`: 18 routes, clean.

**Still to eyeball in a browser** (visual only; data path proven): the streaming chat animation,
the collapsible thinking panel, the dossier rendering inside the iframe, the upload mapping form,
the admin lock affordance.
