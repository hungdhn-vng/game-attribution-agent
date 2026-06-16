import { describe, it, expect, vi, afterEach } from "vitest";
import { callSensorTower } from "../../lib/gaa/st-client";

function jsonResp(body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json", ...headers } });
}

afterEach(() => vi.restoreAllMocks());

describe("callSensorTower", () => {
  it("initializes, calls the tool, returns parsed content", async () => {
    const methods: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      methods.push(rpc.method);
      if (rpc.method === "initialize")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: { protocolVersion: "x", capabilities: {} } },
                        { "mcp-session-id": "S1" });
      if (rpc.method === "tools/call")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: { content: [{ type: "text", text: "{\"rows\":1}" }] } });
      return jsonResp({});
    }));
    const out = await callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "app_performance_api_v2_app_performance_get", params: { app_id: [1] } });
    expect(methods).toEqual(["initialize", "tools/call"]);
    expect(out).toEqual({ rows: 1 });
  });

  it("sends the session id on the tools/call after initialize", async () => {
    const seenSession: (string | null)[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      seenSession.push((init.headers || {})["mcp-session-id"] ?? null);
      if (rpc.method === "initialize")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: {} }, { "mcp-session-id": "SID" });
      return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: { content: [{ type: "text", text: "[]" }] } });
    }));
    await callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "t", params: {} });
    // first call (initialize) has no session id; second (tools/call) carries "SID"
    expect(seenSession[1]).toBe("SID");
  });

  it("throws on a JSON-RPC error", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      if (rpc.method === "initialize") return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: {} });
      return jsonResp({ jsonrpc: "2.0", id: rpc.id, error: { code: -32000, message: "boom" } });
    }));
    await expect(callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "t", params: {} })).rejects.toThrow(/boom/);
  });
});
