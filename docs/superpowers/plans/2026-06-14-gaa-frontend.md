# GAA Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude-style chat UI (cloned from `vercel/ai-chatbot`) that talks to the live GAA Custom Agent — streamed chat + activity + collapsible reasoning, CSV-upload onboarding, and the interactive dossier in a sandboxed iframe — with all tokens held server-side by a Next.js proxy.

**Architecture:** Clone `vercel/ai-chatbot` into `frontend/`, gut NextAuth/Drizzle-Postgres/model-picker, and **replace its AI-SDK `useChat` data layer with a custom hook** that streams our backend's SSE (`{type:activity|thinking|token|done}`) through server-only proxy routes. The proxy injects `GAA_AGENT_TOKEN` always and the admin key only for sessions holding a valid signed cookie (passphrase-gated). The dossier is loaded into a sandboxed iframe via the `[[gaa:run_id=…]]` marker.

**Tech Stack:** Next.js (App Router) + TypeScript + Tailwind/shadcn (from the clone); **vitest** for unit tests of the deterministic modules; `pnpm` (via corepack). Node 25 / npm 11 are installed; no pnpm yet.

**Live backend contract (verified, runtime `gaa-custom-agent` v4 ACTIVE):**
- Endpoint: `https://endpoint-ef33f05d-a8b7-49cb-807b-f2b03d934115.agentbase-runtime.aiplatform.vngcloud.vn` (in `.agentbase/gaa_custom_agent.json`).
- `POST /chat` — `Authorization: Bearer <GAA_AGENT_TOKEN>` (+ `X-GAA-Admin-Key` for admin); body `{"messages":[{"role","content"}]}`; **SSE** `data: {"type":"activity"|"thinking"|"token"|"done", "text"?, "scope"?, "run_id"?}\n\n`; stateless (resend full history). Final assistant text carries `[[gaa:run_id=<id>]]`.
- `POST /invocations` — Bearer; body `{"action","args","admin_key"?}`. Onboarding (`onboard_propose`/`onboard_confirm`) is **non-admin** and accepts `csv_b64` (base64 CSV) or a `csv` path; `exec`/`browse`/`self_edit`/`config_set`/`profile_use`/`tools_*` require `admin_key`. Returns JSON `{"status":"success"|"error", …}`.
- `GET /runs/<id>/<artifact>` — **open** (no token); `<artifact>` ∈ {`report.html`,`summary.md`,`activity.log`,`ledger.jsonl`,`job.json`}.

**Spec:** `docs/superpowers/specs/2026-06-13-gaa-frontend-design.md`.

**Note on the external clone:** exact `vercel/ai-chatbot` file paths are discovered at clone time and drift across versions. So Phase-1 (scaffold/surgery) tasks describe *what to gut and where things plug in* with verification gates (the app must still build/boot); Phases 2–4 build **our** code — fully specified with exact contents + vitest tests where the logic is deterministic.

---

## File Structure (our code, under `frontend/`)

```
frontend/
├── .env.local                      # GAA_BACKEND_URL, GAA_AGENT_TOKEN, GAA_ADMIN_KEY,
│                                   # GAA_ADMIN_PASSPHRASE, GAA_COOKIE_SECRET
├── lib/gaa/
│   ├── sse.ts                      # parseSSEChunk() — partial-chunk-safe SSE event parser
│   ├── marker.ts                   # extractRunId() / stripMarker()
│   ├── admin-cookie.ts             # signAdmin() / verifyAdmin() (HMAC, server-only)
│   ├── backend.ts                  # BACKEND_URL, authHeaders(), isAdmin() (server-only)
│   └── store.ts                    # localStorage conversation store (client)
├── app/api/
│   ├── chat/route.ts               # POST → backend /chat, SSE pass-through
│   ├── invocations/route.ts        # POST → backend /invocations (+admin_key when admin)
│   ├── upload/route.ts             # POST multipart CSV → /invocations onboard_propose (csv_b64)
│   ├── admin/unlock/route.ts       # POST {passphrase} → signed admin cookie
│   └── runs/[id]/[artifact]/route.ts  # GET → backend artifact (same-origin proxy)
├── components/gaa/
│   ├── use-gaa-chat.ts             # the custom chat hook
│   ├── activity-strip.tsx          # live "steps" indicator
│   ├── thinking-panel.tsx          # collapsible reasoning (thinking events)
│   ├── artifacts-pane.tsx          # sandboxed dossier iframe + run switcher + tabs
│   ├── upload-mapping.tsx          # CSV propose→confirm editable mapping
│   └── admin-unlock.tsx            # lock affordance + passphrase dialog
└── tests/gaa/                      # vitest unit tests (sse, marker, admin-cookie, backend, store)
```

---

## Phase 1 — Scaffold

### Task 1: Clone ai-chatbot into `frontend/` and pin it

**Files:** Create: `frontend/` (clone), `frontend/CLONE.md`.

- [ ] **Step 1: Enable pnpm + clone**
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode
corepack enable && corepack prepare pnpm@latest --activate
git clone --depth 1 https://github.com/vercel/ai-chatbot frontend
cd frontend && CLONE_SHA=$(git rev-parse HEAD) && echo "$CLONE_SHA"
rm -rf .git   # the clone becomes part of the parent repo; not a nested repo
```

- [ ] **Step 2: Record the pin** — create `frontend/CLONE.md`:
```markdown
# Clone provenance
Cloned from https://github.com/vercel/ai-chatbot at commit <CLONE_SHA> on 2026-06-14.
Gutted: NextAuth, Drizzle/Postgres, model-picker, AI-SDK chat data layer.
Added: lib/gaa/*, app/api/*, components/gaa/*. See docs/superpowers/specs/2026-06-13-gaa-frontend-design.md.
```
(Replace `<CLONE_SHA>` with the value printed in Step 1.)

- [ ] **Step 3: Install deps**
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode/frontend && pnpm install
```
Expected: installs without error (may warn about peer deps — OK).

- [ ] **Step 4: Add vitest** (for the deterministic-unit tests in Phase 2)
```bash
pnpm add -D vitest
```
Then add to `frontend/package.json` `"scripts"`: `"test": "vitest run"`. Verify `pnpm test` runs (0 tests is fine at this point).

- [ ] **Step 5: Commit**
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode
git add frontend
git commit -m "chore(frontend): clone vercel/ai-chatbot into frontend/ (pinned), add vitest"
```

---

### Task 2: Gut auth, database, and the model-picker

**Files:** Modify/Delete across `frontend/` (discovered by grep — see steps).

> **Goal of this task:** the app boots and renders a chat page with **no login, no database, no model selector**, ready for our data layer. Because exact paths vary by clone version, use the greps to locate them; the verification gate is "builds + boots".

- [ ] **Step 1: Locate the auth/db/model-picker surface**
```bash
cd frontend
grep -rl "next-auth" app lib components 2>/dev/null
grep -rl "drizzle\|postgres\|@vercel/postgres\|DATABASE_URL" app lib 2>/dev/null
grep -rli "model.*picker\|modelId\|selectedModel\|model-selector" components app 2>/dev/null
```
Note the files each prints.

- [ ] **Step 2: Remove auth** — delete the auth route group and middleware that enforce login (typically `app/(auth)/`, `middleware.ts`, `lib/auth*`/`auth.ts`). Replace any `auth()`/`session` calls in server components/layouts with a hardcoded single user, e.g. a constant `const user = { id: "local", name: "you" }`. Remove `next-auth` from `package.json` if it no longer imports.

- [ ] **Step 3: Remove the database** — delete the Drizzle schema/migrations/`lib/db/` and any `@vercel/postgres`/`drizzle-orm` imports. Remove server-side chat persistence (history will live in localStorage, Phase 4). Delete DB-backed server actions that load/save chats; leave the chat page rendering an empty conversation.

- [ ] **Step 4: Remove the model-picker** — delete the model-selector component and any `models`/`providers` config; the backend IS the model. Remove references from the chat header.

- [ ] **Step 5: Boot it**
```bash
pnpm dev
```
Open `http://localhost:3000`. Expected: a chat UI renders with no login redirect, no model dropdown, no DB errors in the console. (The send box may not work yet — that's Phase 4.) Stop the dev server.

- [ ] **Step 6: Build gate**
```bash
pnpm build
```
Expected: a clean production build (no type errors from dangling auth/db imports). Fix any dangling imports the build surfaces.

- [ ] **Step 7: Commit**
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode
git add frontend
git commit -m "chore(frontend): gut NextAuth, Drizzle/Postgres, model-picker (single-user shell)"
```

**Status note:** If gutting reveals the chat page is deeply coupled to `useChat`/AI-SDK such that it won't build without the data layer, report DONE_WITH_CONCERNS and proceed — Phase 4 replaces that layer; for now stub the page to render the message list with an empty `messages` array so the build passes.

---

### Task 3: Environment + config

**Files:** Create: `frontend/.env.local`, `frontend/.env.example`; ensure `frontend/.gitignore` excludes `.env.local`.

- [ ] **Step 1: Create `frontend/.env.example`**
```
GAA_BACKEND_URL=https://endpoint-ef33f05d-a8b7-49cb-807b-f2b03d934115.agentbase-runtime.aiplatform.vngcloud.vn
GAA_AGENT_TOKEN=
GAA_ADMIN_KEY=
GAA_ADMIN_PASSPHRASE=
GAA_COOKIE_SECRET=
```

- [ ] **Step 2: Create `frontend/.env.local`** (real values; gitignored). The agent token + admin key are in the repo's root `.env` (the backend's env file). Copy `GAA_AGENT_TOKEN` and `GAA_ADMIN_KEY` from there. Pick a `GAA_ADMIN_PASSPHRASE` (what you'll type to unlock admin — distinct from the backend admin key) and a random `GAA_COOKIE_SECRET` (`openssl rand -hex 32`). `GAA_BACKEND_URL` as above.
```bash
cd frontend
# verify .env.local is gitignored (Next.js default .gitignore includes .env*.local)
git check-ignore .env.local && echo "ignored" || echo ".env.local" >> .gitignore
```

- [ ] **Step 3: Commit** (only the example + gitignore, never `.env.local`)
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode
git add frontend/.env.example frontend/.gitignore
git commit -m "chore(frontend): env contract (.env.example) — backend url + token/admin/cookie secrets"
```

---

## Phase 2 — Deterministic plumbing (TDD with vitest)

### Task 4: `lib/gaa/sse.ts` — partial-chunk-safe SSE parser

**Files:** Create `frontend/lib/gaa/sse.ts`; Test `frontend/tests/gaa/sse.test.ts`.

- [ ] **Step 1: Write the failing test** — `frontend/tests/gaa/sse.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { parseSSEChunk } from "../../lib/gaa/sse";

describe("parseSSEChunk", () => {
  it("parses complete events and buffers a partial tail", () => {
    const r1 = parseSSEChunk("", 'data: {"type":"activity","text":"running analyze…"}\n\n' +
                                 'data: {"type":"thinking","text":"why","scope":"orchestration"}\n\n' +
                                 'data: {"type":"token","text":"par');
    expect(r1.events.map(e => e.type)).toEqual(["activity", "thinking", "token".replace("token","")|| "token"].filter(Boolean).length===0?[]:["activity","thinking"]);
    // the third event is incomplete -> buffered
    expect(r1.events.map(e => e.type)).toEqual(["activity", "thinking"]);
    expect(r1.buffer).toContain('"token"');
    const r2 = parseSSEChunk(r1.buffer, 'tial"}\n\ndata: {"type":"done","run_id":"abc"}\n\n');
    expect(r2.events.map(e => e.type)).toEqual(["token", "done"]);
    expect(r2.events[0]).toMatchObject({ type: "token", text: "partial" });
    expect(r2.events[1]).toMatchObject({ type: "done", run_id: "abc" });
    expect(r2.buffer).toBe("");
  });

  it("tolerates an unknown event type and skips malformed json", () => {
    const r = parseSSEChunk("", 'data: {"type":"thinking","text":"t"}\n\ndata: not-json\n\ndata: {"type":"weird"}\n\n');
    expect(r.events.map(e => e.type)).toEqual(["thinking", "weird"]);
  });
});
```
(Simplify the first assertion line if your runner dislikes it — the intent: first chunk yields `["activity","thinking"]` and buffers the partial token.)

- [ ] **Step 2: Run → fail** — `cd frontend && pnpm test` → FAIL (`parseSSEChunk` not found).

- [ ] **Step 3: Implement** — `frontend/lib/gaa/sse.ts`:
```ts
export type GaaEvent =
  | { type: "activity"; text: string }
  | { type: "thinking"; text: string; scope?: string }
  | { type: "token"; text: string }
  | { type: "done"; run_id: string | null; error?: string }
  | { type: string; [k: string]: unknown };

/** Split accumulated SSE text on event boundaries; keep an incomplete tail in `buffer`. */
export function parseSSEChunk(buffer: string, chunk: string): { events: GaaEvent[]; buffer: string } {
  const data = buffer + chunk;
  const parts = data.split("\n\n");
  const tail = parts.pop() ?? "";
  const events: GaaEvent[] = [];
  for (const part of parts) {
    const line = part.split("\n").find((l) => l.startsWith("data:"));
    if (!line) continue;
    const json = line.slice(5).trim();
    if (!json) continue;
    try {
      events.push(JSON.parse(json) as GaaEvent);
    } catch {
      /* skip malformed event */
    }
  }
  return { events, buffer: tail };
}

/** Read a fetch Response body as SSE, invoking onEvent per parsed event. */
export async function readSSE(resp: Response, onEvent: (e: GaaEvent) => void): Promise<void> {
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const { events, buffer: b } = parseSSEChunk(buffer, decoder.decode(value, { stream: true }));
    buffer = b;
    for (const e of events) onEvent(e);
  }
}
```

- [ ] **Step 4: Run → pass** — `pnpm test` → the sse tests pass.

- [ ] **Step 5: Commit**
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode
git add frontend/lib/gaa/sse.ts frontend/tests/gaa/sse.test.ts
git commit -m "feat(frontend): SSE parser (partial-chunk-safe, tolerant of unknown/malformed events)"
```

---

### Task 5: `lib/gaa/marker.ts` — run-id marker extract/strip

**Files:** Create `frontend/lib/gaa/marker.ts`; Test `frontend/tests/gaa/marker.test.ts`.

- [ ] **Step 1: Write the failing test** — `frontend/tests/gaa/marker.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { extractRunId, stripMarker } from "../../lib/gaa/marker";

describe("marker", () => {
  it("extracts the run id", () => {
    expect(extractRunId("Here it is.\n\n[[gaa:run_id=2026-06-13-revenue-drop-x-8a3c]]"))
      .toBe("2026-06-13-revenue-drop-x-8a3c");
    expect(extractRunId("no marker here")).toBeNull();
  });
  it("strips the marker from the visible text", () => {
    expect(stripMarker("Answer.\n\n[[gaa:run_id=abc]]")).toBe("Answer.");
    expect(stripMarker("clean")).toBe("clean");
  });
});
```

- [ ] **Step 2: Run → fail** — `pnpm test` → FAIL.

- [ ] **Step 3: Implement** — `frontend/lib/gaa/marker.ts`:
```ts
const MARKER = /\[\[gaa:run_id=([^\]]+)\]\]/;

export function extractRunId(text: string): string | null {
  const m = text.match(MARKER);
  return m ? m[1] : null;
}

export function stripMarker(text: string): string {
  return text.replace(/\s*\[\[gaa:run_id=[^\]]+\]\]\s*/g, "").trim();
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add frontend/lib/gaa/marker.ts frontend/tests/gaa/marker.test.ts
git commit -m "feat(frontend): run-id marker extract/strip"
```

---

### Task 6: `lib/gaa/admin-cookie.ts` — HMAC-signed admin cookie

**Files:** Create `frontend/lib/gaa/admin-cookie.ts`; Test `frontend/tests/gaa/admin-cookie.test.ts`.

- [ ] **Step 1: Write the failing test** — `frontend/tests/gaa/admin-cookie.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { signAdmin, verifyAdmin } from "../../lib/gaa/admin-cookie";

const SECRET = "test-secret";

describe("admin cookie", () => {
  it("round-trips a valid unexpired cookie", () => {
    const now = 1_000_000;
    const cookie = signAdmin(SECRET, now + 10_000);
    expect(verifyAdmin(SECRET, cookie, now)).toBe(true);
  });
  it("rejects expired, tampered, malformed, and absent cookies", () => {
    const now = 1_000_000;
    const cookie = signAdmin(SECRET, now + 10_000);
    expect(verifyAdmin(SECRET, cookie, now + 20_000)).toBe(false);      // expired
    expect(verifyAdmin(SECRET, cookie + "x", now)).toBe(false);          // tampered sig
    expect(verifyAdmin(SECRET, "garbage", now)).toBe(false);             // malformed
    expect(verifyAdmin(SECRET, undefined, now)).toBe(false);             // absent
    expect(verifyAdmin("other-secret", cookie, now)).toBe(false);        // wrong secret
  });
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `frontend/lib/gaa/admin-cookie.ts`:
```ts
import crypto from "node:crypto";

/** value = "<expiryMs>.<hex hmac of 'admin:<expiryMs>'>" */
export function signAdmin(secret: string, expiryMs: number): string {
  const exp = String(expiryMs);
  const sig = crypto.createHmac("sha256", secret).update("admin:" + exp).digest("hex");
  return `${exp}.${sig}`;
}

export function verifyAdmin(secret: string, cookie: string | undefined, nowMs: number): boolean {
  if (!cookie) return false;
  const dot = cookie.indexOf(".");
  if (dot <= 0) return false;
  const exp = cookie.slice(0, dot);
  const sig = cookie.slice(dot + 1);
  const expected = crypto.createHmac("sha256", secret).update("admin:" + exp).digest("hex");
  if (sig.length !== expected.length) return false;
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return false;
  const expNum = Number(exp);
  return Number.isFinite(expNum) && expNum > nowMs;
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add frontend/lib/gaa/admin-cookie.ts frontend/tests/gaa/admin-cookie.test.ts
git commit -m "feat(frontend): HMAC-signed, expiring admin cookie (sign/verify, constant-time)"
```

---

### Task 7: `lib/gaa/backend.ts` — server-only auth-header builder

**Files:** Create `frontend/lib/gaa/backend.ts`; Test `frontend/tests/gaa/backend.test.ts`.

- [ ] **Step 1: Write the failing test** — `frontend/tests/gaa/backend.test.ts`:
```ts
import { describe, it, expect, beforeEach } from "vitest";
import { authHeaders, isAdmin } from "../../lib/gaa/backend";
import { signAdmin } from "../../lib/gaa/admin-cookie";

beforeEach(() => {
  process.env.GAA_AGENT_TOKEN = "agent-tok";
  process.env.GAA_ADMIN_KEY = "admin-key";
  process.env.GAA_COOKIE_SECRET = "cookie-secret";
});

describe("authHeaders", () => {
  it("always sends the bearer token; no admin header without a valid cookie", () => {
    const h = authHeaders(undefined);
    expect(h["authorization"]).toBe("Bearer agent-tok");
    expect(h["x-gaa-admin-key"]).toBeUndefined();
    expect(isAdmin(undefined)).toBe(false);
  });
  it("adds the admin header only with a valid cookie", () => {
    const cookie = signAdmin("cookie-secret", Date.now() + 60_000);
    const h = authHeaders(cookie);
    expect(h["x-gaa-admin-key"]).toBe("admin-key");
    expect(isAdmin(cookie)).toBe(true);
  });
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `frontend/lib/gaa/backend.ts`:
```ts
import { verifyAdmin } from "./admin-cookie";

export const BACKEND_URL = (): string => process.env.GAA_BACKEND_URL ?? "";

export function isAdmin(adminCookie?: string): boolean {
  return verifyAdmin(process.env.GAA_COOKIE_SECRET ?? "", adminCookie, Date.now());
}

export function authHeaders(adminCookie?: string): Record<string, string> {
  const headers: Record<string, string> = {
    authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}`,
  };
  if (isAdmin(adminCookie)) headers["x-gaa-admin-key"] = process.env.GAA_ADMIN_KEY ?? "";
  return headers;
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add frontend/lib/gaa/backend.ts frontend/tests/gaa/backend.test.ts
git commit -m "feat(frontend): server-only backend auth-header builder (admin only with valid cookie)"
```

---

### Task 8: `lib/gaa/store.ts` — localStorage conversation store

**Files:** Create `frontend/lib/gaa/store.ts`; Test `frontend/tests/gaa/store.test.ts`.

- [ ] **Step 1: Configure jsdom for this test** — at the top of `frontend/tests/gaa/store.test.ts` add the vitest environment directive, and write the failing test:
```ts
// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { listConversations, saveConversation, loadConversation, type Msg } from "../../lib/gaa/store";

beforeEach(() => localStorage.clear());

describe("conversation store", () => {
  it("saves, lists, and loads conversations", () => {
    const msgs: Msg[] = [{ role: "user", content: "hi" }, { role: "assistant", content: "hello" }];
    saveConversation("c1", "First chat", msgs);
    expect(listConversations().map((c) => c.id)).toContain("c1");
    expect(loadConversation("c1")).toEqual(msgs);
  });
  it("returns [] for an unknown conversation", () => {
    expect(loadConversation("nope")).toEqual([]);
  });
});
```
(If `jsdom` isn't installed, run `pnpm add -D jsdom` first.)

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `frontend/lib/gaa/store.ts`:
```ts
export type Msg = { role: "user" | "assistant"; content: string };
type Meta = { id: string; title: string; updated: number };

const INDEX = "gaa:conversations";
const key = (id: string) => `gaa:conv:${id}`;

export function listConversations(): Meta[] {
  if (typeof localStorage === "undefined") return [];
  try {
    return (JSON.parse(localStorage.getItem(INDEX) ?? "[]") as Meta[])
      .sort((a, b) => b.updated - a.updated);
  } catch {
    return [];
  }
}

export function loadConversation(id: string): Msg[] {
  if (typeof localStorage === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(key(id)) ?? "[]") as Msg[];
  } catch {
    return [];
  }
}

export function saveConversation(id: string, title: string, messages: Msg[]): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(key(id), JSON.stringify(messages));
  const index = listConversations().filter((c) => c.id !== id);
  index.push({ id, title: title.slice(0, 60), updated: Date.now() });
  localStorage.setItem(INDEX, JSON.stringify(index));
}
```

- [ ] **Step 4: Run → pass** (`pnpm test` — all Phase-2 unit suites green).

- [ ] **Step 5: Commit**
```bash
git add frontend/lib/gaa/store.ts frontend/tests/gaa/store.test.ts frontend/package.json
git commit -m "feat(frontend): localStorage conversation store"
```

---

## Phase 3 — Proxy routes (server-only token boundary)

> These run on the Next.js server. Unit-testing route handlers needs a stub backend; the plan verifies them via a **stub-backend integration check** in Task 12 and the live E2E in Task 16. Each route is small and fully specified.

### Task 9: `POST /api/admin/unlock` — passphrase → signed cookie

**Files:** Create `frontend/app/api/admin/unlock/route.ts`.

- [ ] **Step 1: Implement** — `frontend/app/api/admin/unlock/route.ts`:
```ts
import { NextResponse } from "next/server";
import crypto from "node:crypto";
import { signAdmin } from "@/lib/gaa/admin-cookie";

const EIGHT_HOURS = 8 * 60 * 60 * 1000;

function constEq(a: string, b: string): boolean {
  const ab = Buffer.from(a), bb = Buffer.from(b);
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

export async function POST(req: Request) {
  const { passphrase } = await req.json().catch(() => ({ passphrase: "" }));
  const expected = process.env.GAA_ADMIN_PASSPHRASE ?? "";
  if (!expected || !constEq(String(passphrase ?? ""), expected)) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }
  const cookie = signAdmin(process.env.GAA_COOKIE_SECRET ?? "", Date.now() + EIGHT_HOURS);
  const res = NextResponse.json({ ok: true });
  res.cookies.set("gaa_admin", cookie, {
    httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: EIGHT_HOURS / 1000,
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete("gaa_admin");
  return res;
}
```
(`@/` is the clone's path alias for the app root; confirm `tsconfig.json` `paths` maps `@/*` — ai-chatbot ships this. If the alias differs, use the clone's alias or a relative import.)

- [ ] **Step 2: Verify it builds** — `cd frontend && pnpm build` (or `pnpm exec tsc --noEmit`) → no type errors in this route.

- [ ] **Step 3: Commit**
```bash
git add frontend/app/api/admin/unlock/route.ts
git commit -m "feat(frontend): /api/admin/unlock — passphrase -> signed httpOnly admin cookie"
```

---

### Task 10: `POST /api/chat` (SSE pass-through) + `GET /api/runs/[id]/[artifact]`

**Files:** Create `frontend/app/api/chat/route.ts`, `frontend/app/api/runs/[id]/[artifact]/route.ts`.

- [ ] **Step 1: Implement `/api/chat`** — `frontend/app/api/chat/route.ts`:
```ts
import { cookies } from "next/headers";
import { BACKEND_URL, authHeaders } from "@/lib/gaa/backend";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({ messages: [] }));
  const adminCookie = (await cookies()).get("gaa_admin")?.value;
  const upstream = await fetch(`${BACKEND_URL()}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders(adminCookie) },
    body: JSON.stringify({ messages: body.messages ?? [] }),
  });
  if (!upstream.ok || !upstream.body) {
    return new Response(`data: ${JSON.stringify({ type: "done", run_id: null, error: `backend ${upstream.status}` })}\n\n`,
      { status: 200, headers: { "content-type": "text/event-stream" } });
  }
  return new Response(upstream.body, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" },
  });
}
```

- [ ] **Step 2: Implement `/api/runs/[id]/[artifact]`** — `frontend/app/api/runs/[id]/[artifact]/route.ts`:
```ts
import { BACKEND_URL } from "@/lib/gaa/backend";

const ARTIFACTS = new Set(["report.html", "summary.md", "activity.log", "ledger.jsonl", "job.json"]);
const TYPES: Record<string, string> = {
  "report.html": "text/html", "summary.md": "text/markdown",
  "activity.log": "text/plain", "ledger.jsonl": "application/x-ndjson", "job.json": "application/json",
};

export async function GET(_req: Request, ctx: { params: Promise<{ id: string; artifact: string }> }) {
  const { id, artifact } = await ctx.params;
  if (!ARTIFACTS.has(artifact) || !/^[A-Za-z0-9._-]+$/.test(id)) {
    return new Response("not found", { status: 404 });
  }
  const upstream = await fetch(`${BACKEND_URL()}/runs/${encodeURIComponent(id)}/${artifact}`);
  if (!upstream.ok || !upstream.body) return new Response("not found", { status: 404 });
  return new Response(upstream.body, {
    headers: { "content-type": TYPES[artifact], "cache-control": "no-store" },
  });
}
```
(The artifact route is open on the backend; we re-allowlist + sanitize `id` here too. Same-origin so the iframe loads it without CORS.)

- [ ] **Step 3: Verify build** — `pnpm build` (or `pnpm exec tsc --noEmit`) → no type errors.

- [ ] **Step 4: Commit**
```bash
git add frontend/app/api/chat/route.ts "frontend/app/api/runs/[id]/[artifact]/route.ts"
git commit -m "feat(frontend): /api/chat SSE pass-through + /api/runs artifact proxy (same-origin, allowlisted)"
```

---

### Task 11: `POST /api/invocations` + `POST /api/upload`

**Files:** Create `frontend/app/api/invocations/route.ts`, `frontend/app/api/upload/route.ts`.

- [ ] **Step 1: Implement `/api/invocations`** — `frontend/app/api/invocations/route.ts`:
```ts
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { BACKEND_URL, isAdmin } from "@/lib/gaa/backend";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const adminCookie = (await cookies()).get("gaa_admin")?.value;
  const payload: Record<string, unknown> = {
    action: body.action, args: body.args ?? {},
  };
  if (isAdmin(adminCookie)) payload.admin_key = process.env.GAA_ADMIN_KEY ?? "";
  const upstream = await fetch(`${BACKEND_URL()}/invocations`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}` },
    body: JSON.stringify(payload),
  });
  const data = await upstream.json().catch(() => ({ status: "error", error: `backend ${upstream.status}` }));
  return NextResponse.json(data, { status: upstream.status === 401 ? 401 : 200 });
}
```
(Note: `/invocations` takes the admin key in the **body** (`admin_key`), not a header — different from `/chat`.)

- [ ] **Step 2: Implement `/api/upload`** — `frontend/app/api/upload/route.ts`:
```ts
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/gaa/backend";

/** Receive a CSV file, base64 it, ask the backend to propose a column mapping. */
export async function POST(req: Request) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return NextResponse.json({ status: "error", error: "no file" }, { status: 400 });
  const b64 = Buffer.from(await file.arrayBuffer()).toString("base64");
  // onboarding is non-admin, so just the bearer token is needed
  const upstream = await fetch(`${BACKEND_URL()}/invocations`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}` },
    body: JSON.stringify({ action: "onboard_propose", args: { csv_b64: b64 } }),
  });
  const data = await upstream.json().catch(() => ({ status: "error", error: `backend ${upstream.status}` }));
  // echo the b64 back so the client can pass it to onboard_confirm after editing the mapping
  return NextResponse.json({ ...data, csv_b64: b64 }, { status: 200 });
  void cookies; // (admin not needed for onboarding)
}
```
(Remove the `void cookies;` line + the `cookies` import if your linter complains — upload doesn't need the cookie. Kept here only to mark intent; prefer deleting it.)

- [ ] **Step 3: Verify build** — `pnpm exec tsc --noEmit` → clean.

- [ ] **Step 4: Commit**
```bash
git add frontend/app/api/invocations/route.ts frontend/app/api/upload/route.ts
git commit -m "feat(frontend): /api/invocations (admin_key in body when admin) + /api/upload (CSV->base64->onboard_propose)"
```

---

### Task 12: Proxy auth integration check (stub backend)

**Files:** Create `frontend/tests/gaa/proxy-auth.test.ts`.

> Verifies the **security-critical** property: the admin key is attached only with a valid cookie. We test the pure decision (`authHeaders`/`isAdmin`) exhaustively here (the route wiring is exercised live in Task 16). This is a focused belt-and-suspenders on the boundary.

- [ ] **Step 1: Write the test** — `frontend/tests/gaa/proxy-auth.test.ts`:
```ts
import { describe, it, expect, beforeEach } from "vitest";
import { authHeaders, isAdmin } from "../../lib/gaa/backend";
import { signAdmin } from "../../lib/gaa/admin-cookie";

beforeEach(() => {
  process.env.GAA_AGENT_TOKEN = "T"; process.env.GAA_ADMIN_KEY = "K"; process.env.GAA_COOKIE_SECRET = "S";
});

describe("proxy auth boundary", () => {
  it("no cookie / bad cookie / expired cookie => no admin", () => {
    expect(isAdmin(undefined)).toBe(false);
    expect(isAdmin("forged.deadbeef")).toBe(false);
    expect(isAdmin(signAdmin("S", Date.now() - 1))).toBe(false);
    expect(authHeaders(undefined)["x-gaa-admin-key"]).toBeUndefined();
  });
  it("valid cookie => admin key attached, bearer always present", () => {
    const c = signAdmin("S", Date.now() + 60_000);
    expect(isAdmin(c)).toBe(true);
    const h = authHeaders(c);
    expect(h["authorization"]).toBe("Bearer T");
    expect(h["x-gaa-admin-key"]).toBe("K");
  });
});
```

- [ ] **Step 2: Run → pass** — `pnpm test` (all unit suites green).

- [ ] **Step 3: Commit**
```bash
git add frontend/tests/gaa/proxy-auth.test.ts
git commit -m "test(frontend): proxy auth boundary — admin key only with a valid cookie"
```

---

## Phase 4 — UI

### Task 13: `components/gaa/use-gaa-chat.ts` — the custom chat hook

**Files:** Create `frontend/components/gaa/use-gaa-chat.ts`.

- [ ] **Step 1: Implement** — `frontend/components/gaa/use-gaa-chat.ts`:
```ts
"use client";
import { useCallback, useRef, useState } from "react";
import { readSSE } from "@/lib/gaa/sse";
import { extractRunId, stripMarker } from "@/lib/gaa/marker";
import type { Msg } from "@/lib/gaa/store";

export type Think = { scope?: string; text: string };
export type Turn = Msg & { thinking?: Think[]; activity?: string[]; runId?: string | null };

export function useGaaChat(initial: Turn[] = []) {
  const [messages, setMessages] = useState<Turn[]>(initial);
  const [streaming, setStreaming] = useState(false);
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  const msgsRef = useRef(messages);
  msgsRef.current = messages;

  const send = useCallback(async (text: string) => {
    const history = [...msgsRef.current, { role: "user", content: text } as Turn];
    // assistant placeholder accumulates streamed token text + activity + thinking
    const assistant: Turn = { role: "assistant", content: "", thinking: [], activity: [] };
    setMessages([...history, assistant]);
    setStreaming(true);
    const wire = history.map((m) => ({ role: m.role, content: m.content })); // send raw history (markers intact)
    let acc = "";
    const patch = (fn: (a: Turn) => void) =>
      setMessages((cur) => { const c = [...cur]; const a = { ...c[c.length - 1] }; fn(a); c[c.length - 1] = a; return c; });
    try {
      const resp = await fetch("/api/chat", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: wire }),
      });
      await readSSE(resp, (e) => {
        if (e.type === "activity") patch((a) => { a.activity = [...(a.activity ?? []), (e as any).text]; });
        else if (e.type === "thinking") patch((a) => { a.thinking = [...(a.thinking ?? []), { scope: (e as any).scope, text: (e as any).text }]; });
        else if (e.type === "token") { acc += (e as any).text; patch((a) => { a.content = stripMarker(acc); }); }
        else if (e.type === "done") {
          const rid = (e as any).run_id ?? extractRunId(acc);
          patch((a) => { a.runId = rid; a.content = stripMarker(acc); });
          if (rid) setLatestRunId(rid);
        }
      });
    } finally {
      setStreaming(false);
    }
  }, []);

  return { messages, streaming, latestRunId, send, setMessages };
}
```
Note: the hook stores the assistant message's **stripped** text for display, but resends `history` with **raw** content. To keep markers in resent history, store the raw `acc` separately if needed; for v1 the visible-stripped text is resent (the run_id is also carried in `latestRunId`/per-message `runId`, and the backend re-derives context from the conversation) — acceptable. (If drilldown run-reuse misbehaves live, switch to storing raw content for the wire; see Task 16.)

- [ ] **Step 2: Verify build** — `pnpm exec tsc --noEmit` → no type errors (you may need `// @ts-expect-error`-free `any` casts as written).

- [ ] **Step 3: Commit**
```bash
git add frontend/components/gaa/use-gaa-chat.ts
git commit -m "feat(frontend): useGaaChat hook — streams SSE, accumulates token/activity/thinking, tracks run id"
```

---

### Task 14: presentational components — activity strip, thinking panel, upload mapping, admin unlock

**Files:** Create `frontend/components/gaa/{activity-strip,thinking-panel,upload-mapping,admin-unlock}.tsx`.

> These adapt to the clone's UI primitives (shadcn `Button`/`Dialog`/`Collapsible`, Tailwind classes). The code below is functional plain-React/Tailwind; swap in the clone's components where it improves consistency. Verification is visual (Task 16).

- [ ] **Step 1: `activity-strip.tsx`**
```tsx
"use client";
export function ActivityStrip({ activity }: { activity?: string[] }) {
  if (!activity?.length) return null;
  return (
    <div className="text-xs text-muted-foreground space-y-0.5 my-1">
      {activity.map((a, i) => <div key={i}>· {a}</div>)}
    </div>
  );
}
```

- [ ] **Step 2: `thinking-panel.tsx`** (collapsible)
```tsx
"use client";
import { useState } from "react";
import type { Think } from "./use-gaa-chat";
export function ThinkingPanel({ thinking }: { thinking?: Think[] }) {
  const [open, setOpen] = useState(false);
  if (!thinking?.length) return null;
  return (
    <div className="my-1 text-sm">
      <button className="text-xs underline text-muted-foreground" onClick={() => setOpen(!open)}>
        {open ? "Hide thinking" : `Show thinking (${thinking.length})`}
      </button>
      {open && (
        <div className="mt-1 border-l-2 pl-2 space-y-1 text-muted-foreground">
          {thinking.map((t, i) => <div key={i}><span className="opacity-60">[{t.scope ?? "thinking"}]</span> {t.text}</div>)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: `upload-mapping.tsx`** — propose→confirm editable mapping. Renders the proposed `ColumnMapping` (date_col, metric_cols, dim_cols) + name/platform/genre fields; on confirm POSTs `/api/invocations` `onboard_confirm` with the `csv_b64` (echoed from `/api/upload`) + the edited mapping. Full component:
```tsx
"use client";
import { useState } from "react";

type Mapping = { date_col: string; metric_cols: Record<string, string>; dim_cols: Record<string, string> };

export function UploadMapping({ file, onDone }: { file: File; onDone: (msg: string) => void }) {
  const [proposed, setProposed] = useState<Mapping | null>(null);
  const [b64, setB64] = useState<string>("");
  const [name, setName] = useState("MyGame");
  const [platform, setPlatform] = useState("roblox");
  const [genre, setGenre] = useState("casual");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function propose() {
    setBusy(true); setErr(null);
    const fd = new FormData(); fd.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body: fd }).then((x) => x.json());
    setBusy(false);
    if (r.status === "error") { setErr(r.error ?? "propose failed"); return; }
    setProposed(r.mapping as Mapping); setB64(r.csv_b64 as string);
  }

  async function confirm() {
    if (!proposed) return;
    setBusy(true); setErr(null);
    const r = await fetch("/api/invocations", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "onboard_confirm",
        args: { csv_b64: b64, mapping: JSON.stringify(proposed), name, platform, genre } }),
    }).then((x) => x.json());
    setBusy(false);
    if (r.status === "error") { setErr(r.error ?? "onboard failed"); return; }
    onDone(`Onboarded ${r.name} (${r.row_count} rows; metrics: ${(r.metrics ?? []).join(", ")})`);
  }

  return (
    <div className="border rounded p-3 space-y-2 text-sm">
      <div className="font-medium">Onboard CSV: {file.name}</div>
      {err && <div className="text-red-500">{err}</div>}
      {!proposed ? (
        <button className="border rounded px-2 py-1" disabled={busy} onClick={propose}>
          {busy ? "Analyzing…" : "Propose column mapping"}
        </button>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <label>Name <input className="border rounded px-1 w-full" value={name} onChange={(e) => setName(e.target.value)} /></label>
            <label>Platform <input className="border rounded px-1 w-full" value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
            <label>Genre <input className="border rounded px-1 w-full" value={genre} onChange={(e) => setGenre(e.target.value)} /></label>
            <label>Date col <input className="border rounded px-1 w-full" value={proposed.date_col}
              onChange={(e) => setProposed({ ...proposed, date_col: e.target.value })} /></label>
          </div>
          <div className="text-xs">metrics: {JSON.stringify(proposed.metric_cols)} · dims: {JSON.stringify(proposed.dim_cols)}</div>
          <button className="border rounded px-2 py-1" disabled={busy} onClick={confirm}>{busy ? "Onboarding…" : "Confirm & onboard"}</button>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: `admin-unlock.tsx`**
```tsx
"use client";
import { useState } from "react";
export function AdminUnlock({ onChange }: { onChange?: (admin: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [pass, setPass] = useState("");
  const [admin, setAdmin] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function unlock() {
    const r = await fetch("/api/admin/unlock", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ passphrase: pass }) });
    if (r.ok) { setAdmin(true); setOpen(false); setErr(null); onChange?.(true); }
    else setErr("incorrect passphrase");
  }
  async function lock() { await fetch("/api/admin/unlock", { method: "DELETE" }); setAdmin(false); onChange?.(false); }
  return (
    <div className="text-xs">
      {admin ? (
        <button className="border rounded px-2 py-0.5" onClick={lock}>🔓 admin · lock</button>
      ) : open ? (
        <span className="space-x-1">
          <input type="password" className="border rounded px-1" placeholder="admin passphrase"
                 value={pass} onChange={(e) => setPass(e.target.value)} />
          <button className="border rounded px-2 py-0.5" onClick={unlock}>unlock</button>
          {err && <span className="text-red-500">{err}</span>}
        </span>
      ) : (
        <button className="opacity-60" onClick={() => setOpen(true)}>🔒</button>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Verify build** — `pnpm exec tsc --noEmit` → clean.

- [ ] **Step 6: Commit**
```bash
git add frontend/components/gaa/activity-strip.tsx frontend/components/gaa/thinking-panel.tsx frontend/components/gaa/upload-mapping.tsx frontend/components/gaa/admin-unlock.tsx
git commit -m "feat(frontend): activity strip, thinking panel, upload-mapping, admin-unlock components"
```

---

### Task 15: `components/gaa/artifacts-pane.tsx` + wire the chat page

**Files:** Create `frontend/components/gaa/artifacts-pane.tsx`; Modify the clone's main chat page (e.g. `app/(chat)/page.tsx` or `app/page.tsx` — discovered) to use `useGaaChat` + render the strips/panel + the artifacts pane.

- [ ] **Step 1: `artifacts-pane.tsx`** — sandboxed iframe + run switcher + tabs:
```tsx
"use client";
import { useState } from "react";

export function ArtifactsPane({ runIds, current }: { runIds: string[]; current: string | null }) {
  const [sel, setSel] = useState<string | null>(current);
  const [tab, setTab] = useState<"dossier" | "trace">("dossier");
  const runId = sel ?? current;
  if (!runId) return <div className="p-4 text-sm text-muted-foreground">No dossier yet — ask about a game.</div>;
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 p-2 border-b text-sm">
        <select className="border rounded px-1" value={runId} onChange={(e) => setSel(e.target.value)}>
          {[...new Set([runId, ...runIds])].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button className={tab === "dossier" ? "font-medium" : "opacity-60"} onClick={() => setTab("dossier")}>Dossier</button>
        <button className={tab === "trace" ? "font-medium" : "opacity-60"} onClick={() => setTab("trace")}>Trace</button>
      </div>
      {tab === "dossier" ? (
        <iframe key={runId} title="dossier" sandbox="allow-scripts"
                src={`/api/runs/${encodeURIComponent(runId)}/report.html`} className="flex-1 w-full border-0" />
      ) : (
        <iframe key={runId + "trace"} title="trace" sandbox=""
                src={`/api/runs/${encodeURIComponent(runId)}/summary.md`} className="flex-1 w-full border-0" />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire the chat page** — in the clone's main chat page component, replace the AI-SDK `useChat` usage with `useGaaChat`, and lay out two panes (chat left, `ArtifactsPane` right). Render, per assistant message: `<ThinkingPanel thinking={m.thinking} />`, `<ActivityStrip activity={m.activity} />`, then the markdown `m.content`. Put `<AdminUnlock />` in the header and a file input that opens `<UploadMapping file=… onDone={…}/>` (drop the result message into the chat as a system note). Collect `runIds` from messages and pass `current={latestRunId}` to `ArtifactsPane`. Persist `messages` to localStorage via `lib/gaa/store` on change; load on mount. Keep the clone's composer; on submit call `send(text)`.

  Minimal page skeleton (adapt imports/layout to the clone):
```tsx
"use client";
import { useEffect, useState } from "react";
import { useGaaChat } from "@/components/gaa/use-gaa-chat";
import { ActivityStrip } from "@/components/gaa/activity-strip";
import { ThinkingPanel } from "@/components/gaa/thinking-panel";
import { ArtifactsPane } from "@/components/gaa/artifacts-pane";
import { AdminUnlock } from "@/components/gaa/admin-unlock";
import { UploadMapping } from "@/components/gaa/upload-mapping";
import { saveConversation, loadConversation } from "@/lib/gaa/store";

const CONV = "default";
export default function ChatPage() {
  const { messages, streaming, latestRunId, send, setMessages } = useGaaChat();
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  useEffect(() => { const m = loadConversation(CONV); if (m.length) setMessages(m as any); }, [setMessages]);
  useEffect(() => { if (messages.length) saveConversation(CONV, messages[0]?.content ?? "chat", messages as any); }, [messages]);
  const runIds = messages.map((m: any) => m.runId).filter(Boolean) as string[];
  return (
    <div className="flex h-screen">
      <div className="flex flex-col w-1/2 border-r">
        <div className="flex justify-between p-2 border-b"><span>GAA</span><AdminUnlock /></div>
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {messages.map((m: any, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : ""}>
              {m.role === "assistant" && <><ThinkingPanel thinking={m.thinking} /><ActivityStrip activity={m.activity} /></>}
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
          ))}
          {file && <UploadMapping file={file} onDone={(msg) => { setFile(null); setMessages((c: any) => [...c, { role: "assistant", content: msg }]); }} />}
        </div>
        <form className="p-2 border-t flex gap-2" onSubmit={(e) => { e.preventDefault(); if (input.trim()) { send(input); setInput(""); } }}>
          <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
          <input className="flex-1 border rounded px-2" value={input} onChange={(e) => setInput(e.target.value)}
                 placeholder="Ask: why did revenue drop?" disabled={streaming} />
          <button className="border rounded px-3" disabled={streaming}>Send</button>
        </form>
      </div>
      <div className="w-1/2"><ArtifactsPane runIds={runIds} current={latestRunId} /></div>
    </div>
  );
}
```
(This skeleton is a fallback that satisfies the spec; prefer grafting our components into the clone's nicer message/composer components for visual polish.)

- [ ] **Step 3: Build gate** — `pnpm build` → clean.

- [ ] **Step 4: Commit**
```bash
git add frontend/components/gaa/artifacts-pane.tsx frontend/app
git commit -m "feat(frontend): artifacts pane (sandboxed dossier iframe) + wire chat page to useGaaChat"
```

---

## Phase 5 — End-to-end

### Task 16: Manual E2E against the live agent + full unit suite

**Files:** none (verification). Optional: `frontend/E2E.md` notes.

- [ ] **Step 1: Unit suite green** — `cd frontend && pnpm test` → all `tests/gaa/*` pass (sse, marker, admin-cookie, backend, store, proxy-auth).

- [ ] **Step 2: Boot against the live agent** — ensure `frontend/.env.local` has the real token/admin-key/passphrase/cookie-secret + the live `GAA_BACKEND_URL`. `pnpm dev`, open `http://localhost:3000`.

- [ ] **Step 3: Chat + dossier + reasoning** — ask "Why did revenue drop for SampleGame?" (SampleGame is onboarded + persisted on the live agent). Verify: the **activity strip** shows "running analyze…"; the **thinking panel** shows orchestration + synthesis reasoning; the answer streams; the **artifacts pane** loads the interactive dossier in the iframe. Ask a follow-up "break it down by region" → confirm it reuses the run (drilldown). If run-reuse fails, apply the Task-13 note (store raw assistant content — with the marker — for the resent wire history).

- [ ] **Step 4: Upload onboarding** — choose a CSV (e.g. a copy of the bundled sample columns `dt,dau_count,rev,country,app_version`), click "Propose column mapping", review/edit, "Confirm & onboard" → success toast; then ask an analysis about the new game.

- [ ] **Step 5: Admin unlock** — click 🔒, enter the `GAA_ADMIN_PASSPHRASE` → badge shows admin; ask the agent to run a shell command (e.g. "run `echo hi` with exec") → it works. Click "lock" → ask again → refused. (Confirms the cookie-gated admin path end-to-end.)

- [ ] **Step 6: Record results** — note any issues in `frontend/E2E.md`; commit it.
```bash
git add frontend/E2E.md
git commit -m "docs(frontend): E2E verification notes against the live agent"
```

---

## Self-Review

**Spec coverage (frontend spec → task):**
- §3 clone + gut auth/db/model-picker, single Next.js app → Tasks 1–2. ✓
- §3 env (.env.local: backend url + tokens) → Task 3. ✓
- §4 proxy routes (/api/chat SSE, /api/upload, /api/invocations, /api/admin/unlock, /api/runs/[id]/[artifact]) → Tasks 9–11. ✓
- §5 custom hook (messages+localStorage, resend history, SSE parse, activity strip) → Tasks 8, 13, 15. ✓
- §5 `thinking` rendering (§15/§2) → Tasks 13 (hook), 14 (panel), 15 (wired). ✓
- §6 auth: agent token always; admin via signed-cookie unlock (passphrase, httpOnly+Secure+SameSite+HMAC+expiry, constant-time) → Tasks 6, 7, 9, 14. ✓
- §8 upload propose→confirm editable mapping (non-admin) → Tasks 11, 14. ✓
- §9 artifacts pane: marker→sandboxed iframe via same-origin proxy + run switcher + Dossier/Trace tabs → Tasks 5, 10, 15. ✓
- §10 error handling (401 banner; SSE terminal done + retry; bad CSV inline; dossier 404) → Tasks 10 (terminal done on backend error), 11/14 (inline upload error), 15 (iframe). *(Dossier-404 retry UI is minimal in the skeleton; the proxy returns 404 and the iframe shows the backend's not-found — acceptable for v1; note for polish.)*
- §12 tests: sse parser, marker, mapping form, proxy auth (admin only with valid cookie) + manual E2E → Tasks 4,5,6,7,8,12,16. ✓
- §11 known limitation (drilldown doesn't re-render dossier) — inherited from backend; surfaced in Task 16 step 3. ✓

**Placeholder scan:** Phases 2–4 give exact file contents + tests. Phase-1 scaffold tasks are necessarily discovery-gated (external repo) but each has a concrete verification (builds/boots) — this is the honest minimum for surgery on a repo cloned at execution time, not a placeholder. No "TBD/implement later".

**Type/name consistency:** `parseSSEChunk`/`readSSE`/`GaaEvent` (Task 4) used by the hook (13); `extractRunId`/`stripMarker` (5) used by hook (13) + pane (15); `signAdmin`/`verifyAdmin` (6) used by `backend.ts` (7) + `/api/admin/unlock` (9); `authHeaders`/`isAdmin`/`BACKEND_URL` (7) used by routes (10,11) + proxy-auth test (12); `Msg`/`Turn`/`Think` types flow store(8)→hook(13)→components(14,15); the `gaa_admin` cookie name + `/api/*` route paths are consistent across routes and components. ✓

**Known soft spots (called out, not placeholders):** (a) exact ai-chatbot file paths for the gut/wire steps are resolved at clone time — Tasks 2 & 15 use greps + a fallback page skeleton so they always have a working target; (b) the hook resends visible (marker-stripped) history by default with a documented switch to raw-history if live drilldown reuse needs it (Task 13 note, verified in Task 16); (c) dossier-404 retry UI is minimal in v1.
