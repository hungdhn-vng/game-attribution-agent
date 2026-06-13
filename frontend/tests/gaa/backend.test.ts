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
