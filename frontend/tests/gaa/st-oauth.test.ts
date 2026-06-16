import { describe, it, expect } from "vitest";
import { makePkce, buildAuthorizeUrl, tokenIsFresh } from "../../lib/gaa/st-oauth";

describe("st-oauth", () => {
  it("makePkce returns a verifier and S256 challenge", async () => {
    const { verifier, challenge } = await makePkce();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
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
});
