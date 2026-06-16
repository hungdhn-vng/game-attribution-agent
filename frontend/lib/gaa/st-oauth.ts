/**
 * Sensor Tower PKCE OAuth helpers.
 *
 * Connector base URL  → process.env.NEXT_PUBLIC_ST_BASE_URL
 * Client ID           → process.env.NEXT_PUBLIC_ST_CLIENT_ID
 *
 * All helpers are pure functions or thin sessionStorage wrappers so they are
 * easy to unit-test in a Node/vitest environment (no DOM required for the
 * pure helpers; sessionStorage callers are used only in browser code).
 */

// ---------------------------------------------------------------------------
// Internal utilities
// ---------------------------------------------------------------------------

/** Base-64url-encode an ArrayBuffer (no padding, URL-safe chars). */
const b64url = (buf: ArrayBuffer): string =>
  btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StToken = {
  access_token: string;
  refresh_token?: string;
  /** Unix epoch seconds; already has a 60-second safety margin baked in. */
  expiry: number;
};

// ---------------------------------------------------------------------------
// PKCE
// ---------------------------------------------------------------------------

/**
 * Generate a PKCE code_verifier + S256 code_challenge pair.
 * Uses the Web Crypto API (`globalThis.crypto`) available in Node 18+ and all
 * modern browsers.
 */
export async function makePkce(): Promise<{ verifier: string; challenge: string }> {
  const bytes = crypto.getRandomValues(new Uint8Array(48));
  const verifier = b64url(bytes.buffer as ArrayBuffer);
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return { verifier, challenge: b64url(digest) };
}

// ---------------------------------------------------------------------------
// Authorization URL
// ---------------------------------------------------------------------------

export function buildAuthorizeUrl(o: {
  base: string;
  clientId: string;
  redirectUri: string;
  state: string;
  challenge: string;
}): string {
  const q = new URLSearchParams({
    response_type: "code",
    client_id: o.clientId,
    redirect_uri: o.redirectUri,
    scope: "openid",
    state: o.state,
    code_challenge: o.challenge,
    code_challenge_method: "S256",
  });
  return `${o.base.replace(/\/$/, "")}/authorize?${q.toString()}`;
}

// ---------------------------------------------------------------------------
// Token exchange
// ---------------------------------------------------------------------------

/**
 * Exchange an authorization code for tokens at the ST `/token` endpoint.
 * The returned `expiry` is pre-reduced by 60 seconds so callers never use a
 * token that is about to expire.
 */
export async function exchangeCode(o: {
  base: string;
  clientId: string;
  redirectUri: string;
  code: string;
  verifier: string;
}): Promise<StToken> {
  const r = await fetch(`${o.base.replace(/\/$/, "")}/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: o.code,
      redirect_uri: o.redirectUri,
      code_verifier: o.verifier,
      client_id: o.clientId,
    }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`token exchange ${r.status}: ${body}`);
  }
  const d = (await r.json()) as {
    access_token: string;
    refresh_token?: string;
    expires_in?: number;
  };
  return {
    access_token: d.access_token,
    refresh_token: d.refresh_token,
    expiry: Math.floor(Date.now() / 1000) + (d.expires_in ?? 3600) - 60,
  };
}

// ---------------------------------------------------------------------------
// sessionStorage token store (browser-only)
// ---------------------------------------------------------------------------

const KEY = "st_token";

export const getToken = (): StToken | null => {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "null") as StToken | null;
  } catch {
    return null;
  }
};

export const setToken = (t: StToken): void =>
  sessionStorage.setItem(KEY, JSON.stringify(t));

// ---------------------------------------------------------------------------
// Freshness check
// ---------------------------------------------------------------------------

/**
 * Returns true iff `t` is non-null and `nowSec` is strictly before `t.expiry`.
 * @param t       Token object (or null if none stored).
 * @param nowSec  Current time in Unix epoch seconds.
 */
export const tokenIsFresh = (t: StToken | null, nowSec: number): boolean =>
  !!t && nowSec < t.expiry;
