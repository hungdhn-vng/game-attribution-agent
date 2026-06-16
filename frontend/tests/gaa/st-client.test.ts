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
    // MCP order: initialize → initialized notification → tools/call (matches the live wire trace).
    expect(methods).toEqual(["initialize", "notifications/initialized", "tools/call"]);
    expect(out).toEqual({ rows: 1 });
  });

  it("sends the session id on the notification + tools/call after initialize", async () => {
    const seen: Record<string, string | null> = {};
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      seen[rpc.method] = (init.headers || {})["mcp-session-id"] ?? null;
      if (rpc.method === "initialize")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: {} }, { "mcp-session-id": "SID" });
      return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: { content: [{ type: "text", text: "[]" }] } });
    }));
    await callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "t", params: {} });
    expect(seen["initialize"]).toBeNull();                       // no session yet
    expect(seen["notifications/initialized"]).toBe("SID");       // captured from initialize response
    expect(seen["tools/call"]).toBe("SID");
  });

  it("throws on a tool-level error (isError) so it is never cached", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      if (rpc.method === "initialize") return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: {} }, { "mcp-session-id": "S" });
      if (rpc.method === "tools/call")
        return jsonResp({ jsonrpc: "2.0", id: rpc.id,
          result: { isError: true, content: [{ type: "text", text: "HTTP error 429: budget" }] } });
      return jsonResp({});
    }));
    await expect(callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "t", params: {} })).rejects.toThrow(/429/);
  });

  it("throws (not crashes) on an event-stream response with no data line", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      const rpc = JSON.parse(init.body);
      if (rpc.method === "initialize") return jsonResp({ jsonrpc: "2.0", id: rpc.id, result: {} });
      return new Response(": keepalive\n\n", { status: 200, headers: { "content-type": "text/event-stream" } });
    }));
    await expect(callSensorTower({ access_token: "AT", expiry: 9e9 },
      { req_id: "R", st_tool: "t", params: {} })).rejects.toThrow(/no data line/);
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
