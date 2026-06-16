import type { StToken } from "./st-oauth";

const BASE = () =>
  (process.env.NEXT_PUBLIC_ST_BASE_URL || "https://stg-aawp-connector.vnggames.net/sensor-tower-v2").replace(/\/$/, "");

// req_id is the relay's correlation id; it's carried for symmetry but NOT forwarded to ST.
type Built = { req_id: string; st_tool: string; params: Record<string, unknown> };

function parseRpcBody(text: string, contentType: string): any {
  if (!contentType.includes("text/event-stream")) return JSON.parse(text);
  const dataLine = text.split("\n").filter((l) => l.startsWith("data:")).pop();
  if (!dataLine) throw new Error("ST rpc: event-stream response had no data line");
  return JSON.parse(dataLine.slice(5).trim());
}

function mcpHeaders(token: string, sessionId?: string): Record<string, string> {
  const headers: Record<string, string> = {
    authorization: `Bearer ${token}`,
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;
  return headers;
}

async function rpc(method: string, params: unknown, token: string, sessionId?: string) {
  const resp = await fetch(BASE(), {
    method: "POST",
    headers: mcpHeaders(token, sessionId),
    body: JSON.stringify({ jsonrpc: "2.0", id: Math.floor(Math.random() * 1e9), method, params }),
  });
  if (!resp.ok) throw new Error(`ST ${method} ${resp.status}`);
  const sid = resp.headers.get("mcp-session-id") || sessionId;
  const ct = resp.headers.get("content-type") || "";
  const json = parseRpcBody(await resp.text(), ct);
  if (json.error) throw new Error(json.error.message || "ST rpc error");
  return { result: json.result, sessionId: sid };
}

export async function callSensorTower(token: StToken, built: Built): Promise<unknown> {
  const init = await rpc("initialize", {
    protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "gaa-frontend", version: "1" },
  }, token.access_token);
  // MCP requires the initialized notification before requests; real ST rejects tools/call without it.
  // It's a notification (no id) → fire and ignore the (often 202/empty) body.
  await fetch(BASE(), {
    method: "POST",
    headers: mcpHeaders(token.access_token, init.sessionId),
    body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }),
  }).catch(() => {});
  const out = await rpc("tools/call", { name: built.st_tool, arguments: built.params },
                        token.access_token, init.sessionId);
  const result = (out.result ?? {}) as { content?: Array<{ type: string; text?: string }>; isError?: boolean };
  const texts = (result.content ?? []).filter((c) => c.type === "text" && c.text).map((c) => c.text!);
  // ST returns tool-level failures as HTTP 200 + isError:true (e.g. bad app_id, or "HTTP error 429").
  // Throw so the caller maps it to a structured error and the runtime never CACHES an error result.
  if (result.isError) throw new Error(texts.join("") || "Sensor Tower tool error");
  try { return JSON.parse(texts.join("")); } catch { return texts; }
}
