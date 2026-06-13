import { describe, it, expect, beforeEach } from "vitest";
import { authHeaders, isAdmin } from "../../lib/gaa/backend";
import { signAdmin } from "../../lib/gaa/admin-cookie";

beforeEach(() => {
  process.env.GAA_AGENT_TOKEN = "T";
  process.env.GAA_ADMIN_KEY = "K";
  process.env.GAA_COOKIE_SECRET = "S";
});

describe("proxy auth boundary", () => {
  it("no cookie / bad cookie / expired cookie => no admin", () => {
    expect(isAdmin(undefined)).toBe(false);
    expect(isAdmin("forged.deadbeef")).toBe(false);
    expect(isAdmin(signAdmin("S", Date.now() - 1))).toBe(false);
    expect(authHeaders(undefined)["x-gaa-admin-key"]).toBeUndefined();
    // a cookie signed with the WRONG secret must not grant admin
    expect(isAdmin(signAdmin("WRONG", Date.now() + 60_000))).toBe(false);
  });
  it("valid cookie => admin key attached, bearer always present", () => {
    const c = signAdmin("S", Date.now() + 60_000);
    expect(isAdmin(c)).toBe(true);
    const h = authHeaders(c);
    expect(h["authorization"]).toBe("Bearer T");
    expect(h["x-gaa-admin-key"]).toBe("K");
  });
});
