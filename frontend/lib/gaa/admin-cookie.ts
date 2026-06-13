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
