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
    expect(verifyAdmin(SECRET, cookie, now + 20_000)).toBe(false);  // expired
    expect(verifyAdmin(SECRET, cookie + "x", now)).toBe(false);      // tampered sig
    expect(verifyAdmin(SECRET, "garbage", now)).toBe(false);         // malformed
    expect(verifyAdmin(SECRET, undefined, now)).toBe(false);         // absent
    expect(verifyAdmin("other-secret", cookie, now)).toBe(false);    // wrong secret
  });
});
