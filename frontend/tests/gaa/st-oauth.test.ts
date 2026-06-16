import { describe, it, expect, vi, afterEach } from "vitest";
import { makePkce, buildAuthorizeUrl, tokenIsFresh, exchangeCode } from "../../lib/gaa/st-oauth";

describe("st-oauth", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("makePkce returns a verifier and S256 challenge", async () => {
    const { verifier, challenge } = await makePkce();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/);  // base64url, no padding
    expect(verifier).not.toContain("=");
    expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(challenge).not.toContain("=");
  });
  it("buildAuthorizeUrl includes pkce + state + scope", () => {
    const url = buildAuthorizeUrl({ base: "https://h.test/st", clientId: "cid",
      redirectUri: "https://app.test/sensor-tower/connected", state: "S", challenge: "C" });
    expect(url).toContain("https://h.test/st/authorize?");
    expect(url).toContain("client_id=cid");
    expect(url).toContain("code_challenge=C");
    expect(url).toContain("code_challenge_method=S256");
    expect(url).toContain("state=S");
    expect(url).toContain("scope=openid");
  });
  it("tokenIsFresh respects expiry", () => {
    expect(tokenIsFresh({ access_token: "a", expiry: 1000 }, 900)).toBe(true);
    expect(tokenIsFresh({ access_token: "a", expiry: 1000 }, 1001)).toBe(false);
    expect(tokenIsFresh(null, 0)).toBe(false);
  });

  it("exchangeCode posts the form and returns a token with an expiry margin", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ access_token: "AT", refresh_token: "RT", expires_in: 3600 }),
                   { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const t = await exchangeCode({ base: "https://h.test/st", clientId: "cid",
      redirectUri: "https://app.test/cb", code: "CODE", verifier: "V" });
    expect(t.access_token).toBe("AT");
    expect(t.refresh_token).toBe("RT");
    expect(t.expiry).toBeGreaterThan(Math.floor(Date.now() / 1000));  // future, minus 60s margin
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://h.test/st/token");
    expect(String(init.body)).toContain("grant_type=authorization_code");
  });

  it("exchangeCode throws with the server error body on non-ok", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response("invalid_grant: code used", { status: 400 })));
    await expect(exchangeCode({ base: "https://h.test/st", clientId: "cid",
      redirectUri: "https://app.test/cb", code: "BAD", verifier: "V" }))
      .rejects.toThrow(/400: invalid_grant/);
  });
});
