# GAA Frontend — Design (Claude-style chat UI for the Custom Agent)

**Status:** Approved design (pre-implementation)
**Date:** 2026-06-13
**Depends on:** the deployed GAA Custom Agent backend (`docs/superpowers/specs/2026-06-13-gaa-custom-agent-design.md`, runtime `gaa-custom-agent` v3, ACTIVE). This spec also defines **two small backend additions** (§7) that ship with this project.
**Scope:** the **frontend** — a single Next.js app (cloned from `vercel/ai-chatbot`) that talks to the agent: chat with streamed activity, CSV upload → onboarding, and an interactive dossier pane.

---

## 1. Why this exists

The backend can chat, analyze, and serve a byte-exact interactive dossier over HTTP, but it has no UI. This frontend delivers the Claude-style experience the project set out to build: a chat where you ask "why did revenue drop?", watch the agent work, and get an **interactive HTML dossier** rendered inline — plus drag-and-drop **CSV onboarding**. It clones `vercel/ai-chatbot` for its polished UI and scaffolding, swaps the data layer to speak the agent's protocol, and keeps all secrets server-side.

## 2. Goals / non-goals

**Goals**
- A two-pane Claude-style UI: conversation on the left, an **artifacts pane** (the dossier) on the right.
- Stream the agent's work: the final narration streams in; `activity` events show as a live "steps" strip ("running analyze…").
- Detect the `[[gaa:run_id=…]]` marker → render `report.html` in a **sandboxed iframe**.
- **CSV upload → onboarding** (propose → confirm) available to normal (non-admin) users.
- **Per-session admin unlock** (passphrase) for the dangerous toolset (`exec`/`browse`/`self_edit`/config/tools).
- All backend secrets (`GAA_AGENT_TOKEN`, `GAA_ADMIN_KEY`) live only on the Next.js server; the browser never sees them.

**Non-goals**
- Real LLM token-streaming of synthesis *reasoning* (backend defers `show_thinking`; "thinking" here = the `activity` steps).
- Multi-tenant data isolation (one backend, shared profiles/runs — matches the backend's stance).
- A user database / accounts (history is browser-local; admin is a per-session passphrase unlock, not user accounts).
- Re-rendering a dossier after a drilldown (see §11 known limitation).

## 3. Architecture

A single **Next.js (App Router)** app, cloned from `vercel/ai-chatbot`, run locally (`pnpm dev` / `pnpm start`).

**Kept from the clone:** the chat shell + composer + message list, the artifact/canvas pane pattern, Tailwind/shadcn styling, file-attachment UI.
**Gutted:** NextAuth, Drizzle/Postgres, the model picker, server-side chat persistence, the AI-SDK `useChat` data layer.

```
gaa-frontend/                     (cloned + trimmed vercel/ai-chatbot)
├── app/
│   ├── (chat)/page.tsx           # the two-pane chat UI
│   └── api/
│       ├── chat/route.ts         # POST → proxy to backend /chat (SSE pass-through)
│       ├── upload/route.ts       # POST (multipart CSV) → backend onboarding (base64)
│       ├── invocations/route.ts  # POST → backend /invocations (onboard confirm, status)
│       ├── admin/unlock/route.ts # POST {passphrase} → set signed admin cookie
│       └── runs/[id]/[artifact]/route.ts  # GET → proxy backend artifact (same-origin)
├── lib/
│   ├── backend.ts                # server-only: base URL + auth header injection + admin-cookie check
│   ├── sse.ts                    # SSE event parser ({type:activity|token|done})
│   └── store.ts                  # localStorage conversation store
├── components/
│   ├── chat.tsx / message.tsx / composer.tsx   # adapted from the clone
│   ├── activity-strip.tsx        # live "steps" indicator (activity events)
│   ├── artifacts-pane.tsx        # dossier iframe + run switcher + trace tab
│   ├── upload-mapping.tsx        # CSV mapping propose/confirm form
│   └── admin-unlock.tsx          # lock affordance + passphrase dialog
└── .env.local                    # GAA_BACKEND_URL, GAA_AGENT_TOKEN, GAA_ADMIN_KEY,
                                   # GAA_ADMIN_PASSPHRASE, GAA_COOKIE_SECRET
```

**The chat data layer is custom (Approach A).** We do not bend the agent's protocol to the Vercel AI SDK. A small hook owns `messages[]` and streams the backend SSE through the proxy. (Rejected: translating to the AI-SDK data-stream protocol — a fiddly shim for no benefit since we own both ends; and non-streaming — kills the live activity feel.)

## 4. The server proxy (the token boundary)

All backend calls go through **server-only route handlers** (`app/api/*`). `lib/backend.ts` reads the env secrets and the admin cookie; the browser never receives a token.

| Route | Proxies to | Auth attached |
|---|---|---|
| `POST /api/chat` | backend `POST /chat` (SSE) | `Authorization: Bearer GAA_AGENT_TOKEN`; **`X-GAA-Admin-Key: GAA_ADMIN_KEY` iff the request carries a valid admin cookie** |
| `POST /api/upload` | backend onboarding (base64) | Bearer (onboarding is non-admin, §7) |
| `POST /api/invocations` | backend `POST /invocations` | Bearer; `admin_key` iff valid admin cookie |
| `GET /api/runs/[id]/[artifact]` | backend `GET /runs/<id>/<artifact>` (open) | none (open route); same-origin for the iframe |
| `POST /api/admin/unlock` | — (handled in proxy) | sets the admin cookie (see §6) |

`/api/chat` streams the backend response body straight through (`Response(backendResp.body, {headers:{'content-type':'text/event-stream'}})`) — no buffering, so tokens/activity arrive live.

## 5. Chat data layer + UI

- **State:** a `useGaaChat` hook holds `messages: {role, content}[]` in React state, mirrored to **localStorage** (per-conversation key). A sidebar lists saved conversations (localStorage).
- **Send:** POST the **full** `messages[]` to `/api/chat` (stateless backend → resend history each turn; this is what makes **run_id reuse / drilldowns** work).
- **Stream parse (`lib/sse.ts`):** read the response as a stream, split on `\n\n`, `JSON.parse` each `data:` line →
  - `activity` → push onto a transient **steps strip** for the in-flight turn ("running analyze…", "running segments…").
  - `token` → append to the in-flight assistant message (streamed text).
  - `done` → finalize; capture `run_id`.
- **Render:** message list (user + assistant bubbles, markdown); while streaming, the activity strip shows the live steps; the assistant's `[[gaa:run_id=…]]` marker is **stripped from the visible text** (kept in the stored message so re-sent history carries it for reuse).
- **Persistence detail:** the stored assistant message keeps the raw marker; the *rendered* view strips it.

## 6. Auth & per-session admin unlock

**Two backend gates, both enforced server-side by the proxy:**
- **Agent token** (`GAA_AGENT_TOKEN`): attached to *every* backend call. So every app user can chat, upload, analyze, and view dossiers. (If the env var is missing, the proxy returns a clear 500 "agent token not configured" rather than calling the backend.)
- **Admin** (`GAA_ADMIN_KEY`): attached **only** for requests from an unlocked admin session.

**Unlock flow (no user DB):**
1. UI lock affordance → passphrase dialog → `POST /api/admin/unlock {passphrase}`.
2. Proxy **constant-time** compares to `GAA_ADMIN_PASSPHRASE` (a server-side secret, distinct from the backend's `GAA_ADMIN_KEY` — the user never knows the backend key). Light in-memory rate-limiting (e.g. ≤5 attempts/min/IP) to blunt brute force.
3. On match: set cookie `gaa_admin` = `<expiry>.<HMAC_SHA256(GAA_COOKIE_SECRET, "admin:"+expiry)>`, **httpOnly + Secure + SameSite=Lax**, expiry ~8h.
4. Every `/api/chat` + `/api/invocations` verifies the cookie (recompute HMAC, check expiry, constant-time). Valid → attach the admin key; invalid/absent → don't.
5. UI shows an "admin" badge when unlocked; a "lock" button clears the cookie.

**Net:** the backend never identifies clients — it only sees "valid admin key present or not." The *proxy* distinguishes sessions via the signed cookie, gated by the passphrase. One instance serves visitors (upload+analyze) and you (full toolset after unlock). Because the proxy sends the admin key on admin `/chat` calls, the backend builds the admin system prompt (exposing `exec`/`browse`/`self_edit` to the model) for those sessions only.

## 7. Backend additions (small; ship with this project, TDD'd)

Both in `src/gaa/server/`, with pytest:

1. **Onboard from uploaded content.** A new action `onboard_propose_upload` (and/or extend `onboard_propose`/`onboard_confirm`) accepting **base64 CSV content** instead of a path: decode → write to a temp file under the run/scratch area → call the existing onboarding logic. Keeps `/invocations` as the single structured entrypoint; `/api/upload` decodes the multipart file to base64 and calls it.
2. **Reclassify onboarding as non-admin.** Remove `onboard_propose`, `onboard_confirm` (and the new upload action) from `ADMIN_ACTIONS` so the agent token alone authorizes them; keep them in `MUTATING_ACTIONS` (they still snapshot to vStorage). `exec`/`browse`/`self_edit`/`config_set`/`profile_use`/`tools_*` stay admin-gated.

No other backend changes; the agent loop, persistence, and artifact routes are untouched.

## 8. CSV upload → onboarding UX (propose → confirm)

1. User attaches a CSV in the composer → `POST /api/upload` (multipart).
2. Proxy base64-encodes the file → backend `onboard_propose_upload` → LLM infers a `ColumnMapping` (date / metrics / dims) → returns the proposed mapping + a confirmation message.
3. UI renders an **editable mapping form** (`upload-mapping.tsx`): date column, metric columns→canonical names, dim columns→canonical names, plus name/platform/genre fields. Pre-filled from the proposal.
4. Confirm → `POST /api/invocations` `onboard_confirm` (with the same base64 content + the edited mapping) → toast "Onboarded *MyGame* (N rows; metrics: …)".
5. The onboarded game becomes the active profile; the user then asks "why did revenue drop?" and analysis runs against it.

## 9. Artifacts pane (the dossier)

- On each finalized assistant turn, scan for `[[gaa:run_id=…]]`. If present (and not already shown), open the **artifacts pane** and load `GET /api/runs/<id>/report.html` into a **sandboxed iframe** (`sandbox="allow-scripts"`, `src` = the same-origin proxy route). The 4.58 MB self-contained Plotly HTML renders directly.
- **Run switcher:** a dropdown lists every `run_id` seen in the conversation, so the user can flip between dossiers.
- **Tabs:** *Dossier* (`report.html`) | *Trace* (`summary.md` rendered as markdown; `activity.log` as a step list) — fetched from the proxy artifact route.
- **States:** loading spinner while the iframe loads; if `report.html` 404s (run still rendering / errored), show "dossier rendering…" with a retry that re-fetches.

## 10. Error handling

- **Backend 401** (token misconfigured) → the proxy surfaces a single clear banner "Agent auth misconfigured — check GAA_AGENT_TOKEN"; not shown as a chat message.
- **SSE mid-stream error** → the backend always emits a terminal `done` (its own guard); if the connection drops, the hook ends the turn and offers **Retry** (re-POST the same `messages[]`).
- **Upload / bad CSV** → `onboard_propose` returns `{status:"error",…}` → inline error on the upload form (no crash).
- **Dossier 404** → handled in §9 (retry).
- **Admin unlock fail** → dialog shows "incorrect passphrase"; rate-limit message after repeated attempts.

## 11. Known limitation (documented, not fixed in v1)

A `segments`/drilldown enriches the run's ledger + the chat answer but does **not** re-render `report.html` (the backend only re-renders on `report`). So a drilldown shows in chat but not in the existing dossier. **v1 accepts this**; the chat answer conveys the drilldown. Future: nudge the backend persona/system-prompt to call `report` after a drilldown so the dossier updates (a backend-side change, out of this spec).

## 12. Testing

- **Unit:** `lib/sse.ts` parser (feed a scripted byte stream of `data:` lines → assert activity/token/done sequencing + partial-chunk handling); the marker detector/stripper; the mapping-confirm form (proposal → editable → payload).
- **Proxy routes:** integration tests against a **stub backend** (a local server returning canned SSE / JSON) — assert the agent token is attached, the admin key is attached **only** with a valid cookie, `/api/admin/unlock` sets/rejects cookies, and the artifact route proxies bytes.
- **Backend additions:** pytest for `onboard_propose_upload` (base64 round-trip → profile created) and the non-admin gating change (onboarding succeeds without admin; `exec` still refused without admin).
- **Manual E2E** (against the live agent): upload a CSV → confirm mapping → "why did revenue drop?" → dossier renders in the iframe; a follow-up drilldown reuses the run; "analyze again" opens a new dossier; admin unlock → an `exec`/`browse` request works; lock → it's refused again.

## 13. Key decisions

| Decision | Alternative | Why |
|---|---|---|
| Clone ai-chatbot, swap the data layer | build from scratch; or keep AI-SDK useChat | reuse the polished UI; our custom SSE doesn't fit the AI-SDK protocol cleanly |
| Custom hook + SSE pass-through | translate to AI-SDK data stream | no translation shim; full control over activity/marker; we own both ends |
| localStorage history | DB; in-memory | single-user demo; survives refresh; lets us gut Postgres |
| Server proxy holds tokens | tokens in the browser | the agent token = RCE-capable; must never reach the client |
| Per-session admin unlock (passphrase + signed cookie) | instance-level; full login/roles | mixed users on one instance (visitors upload+analyze; you unlock RCE) without a user DB (user choice) |
| Onboarding non-admin (backend reclass) | keep onboarding admin-gated | normal users must be able to upload+analyze (user choice) |
| Upload: propose → confirm | one-shot auto-onboard | robust + Claude-like; the LLM proposes, the user verifies the mapping |
| Dossier via same-origin proxy iframe | iframe directly at the backend URL | same-origin simplifies CSP/sandbox + lets us add headers later |

## 14. Risks / open items

1. **ai-chatbot drift** — the upstream repo changes; we pin a known-good commit when cloning and document it.
2. **SSE buffering** — some hosts buffer streamed responses; for local `pnpm dev`/`start` this is fine; if deployed later, verify the platform streams `text/event-stream` (Vercel does).
3. **Large dossier in an iframe** — 4.58 MB inline Plotly loads fine; if dossiers grow, the backend can switch to CDN-Plotly (its concern, not the frontend's).
4. **Admin cookie hygiene** — must be httpOnly+Secure+SameSite+expiring+HMAC-signed; `GAA_COOKIE_SECRET` is a real secret. Documented in §6.
5. **Mapping-confirm complexity** — inferring + editing column mappings is the fiddliest UI; keep it a simple table; the LLM proposal does the heavy lifting.
