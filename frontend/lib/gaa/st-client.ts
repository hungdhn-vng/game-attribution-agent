import type { StToken } from "./st-oauth";

const BASE = () =>
  (process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2").replace(/\/$/, "");

type Built = { req_id: string; st_tool: string; params: Record<string, unknown> };

async function rpc(method: string, params: unknown, token: string, sessionId?: string) {
  const headers: Record<string, string> = {
    authorization: `Bearer ${token}`,
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;
  const resp = await fetch(BASE(), {
    method: "POST",
    headers,
    body: JSON.stringify({ jsonrpc: "2.0", id: Math.floor(Math.random() * 1e9), method, params }),
  });
  if (!resp.ok) throw new Error(`ST ${method} ${resp.status}`);
  const sid = resp.headers.get("mcp-session-id") || sessionId;
  const ct = resp.headers.get("content-type") || "";
  const text = await resp.text();
  const json = ct.includes("text/event-stream")
    ? JSON.parse(text.split("\n").filter((l) => l.startsWith("data:")).pop()!.slice(5).trim())
    : JSON.parse(text);
  if (json.error) throw new Error(json.error.message || "ST rpc error");
  return { result: json.result, sessionId: sid };
}

export async function callSensorTower(token: StToken, built: Built): Promise<unknown> {
  const init = await rpc("initialize", {
    protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "gaa-frontend", version: "1" },
  }, token.access_token);
  const out = await rpc("tools/call", { name: built.st_tool, arguments: built.params },
                        token.access_token, init.sessionId);
  const content = (out.result?.content ?? []) as Array<{ type: string; text?: string }>;
  const texts = content.filter((c) => c.type === "text" && c.text).map((c) => c.text!);
  try { return JSON.parse(texts.join("")); } catch { return texts; }
}
