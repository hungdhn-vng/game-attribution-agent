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
