import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { fulfillSensorTower } from "../../components/gaa/use-gaa-chat";

// minimal sessionStorage shim for the node env
beforeEach(() => {
  const store: Record<string, string> = {};
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
  });
});
afterEach(() => vi.restoreAllMocks());

describe("fulfillSensorTower", () => {
  it("posts not_connected when there is no token", async () => {
    const posts: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: any, init: any) => {
      posts.push(JSON.parse(init.body));
      return new Response(JSON.stringify({ status: "success" }), { status: 200 });
    }));
    await fulfillSensorTower({ req_id: "R", st_tool: "t", params: {} });
    expect(posts).toHaveLength(1);
    expect(posts[0]).toEqual({ req_id: "R", error: { kind: "not_connected" } });
  });

  it("posts the ST result when connected", async () => {
    sessionStorage.setItem("st_token", JSON.stringify({ access_token: "AT", expiry: 9e9 }));
    const posts: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: any, init: any) => {
      // the ST MCP calls go to the ST base; the fulfill POST goes to /api/sensor-tower/fulfill
      if (String(url).includes("/api/sensor-tower/fulfill")) {
        posts.push(JSON.parse(init.body));
        return new Response(JSON.stringify({ status: "success" }), { status: 200 });
      }
      // mock the ST MCP initialize + tools/call
      const rpc = JSON.parse(init.body);
      if (rpc.method === "initialize")
        return new Response(JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result: {} }),
                            { status: 200, headers: { "content-type": "application/json", "mcp-session-id": "S" } });
      return new Response(JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result: { content: [{ type: "text", text: "{\"ok\":1}" }] } }),
                          { status: 200, headers: { "content-type": "application/json" } });
    }));
    await fulfillSensorTower({ req_id: "R2", st_tool: "app_x", params: { app_id: [1] } });
    const fulfill = posts.find((p) => p.req_id === "R2");
    expect(fulfill).toEqual({ req_id: "R2", result: { ok: 1 } });
  });

  it("posts upstream_error when the ST call throws", async () => {
    sessionStorage.setItem("st_token", JSON.stringify({ access_token: "AT", expiry: 9e9 }));
    const posts: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: any, init: any) => {
      if (String(url).includes("/api/sensor-tower/fulfill")) {
        posts.push(JSON.parse(init.body));
        return new Response(JSON.stringify({ status: "success" }), { status: 200 });
      }
      return new Response("nope", { status: 500 });  // ST initialize fails → callSensorTower throws
    }));
    await fulfillSensorTower({ req_id: "R3", st_tool: "t", params: {} });
    const fulfill = posts.find((p) => p.req_id === "R3");
    expect(fulfill).toMatchObject({ req_id: "R3", error: { kind: "upstream_error", detail: expect.stringContaining("500") } });
  });

  it("maps a 429 to budget_exceeded", async () => {
    sessionStorage.setItem("st_token", JSON.stringify({ access_token: "AT", expiry: 9e9 }));
    const posts: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: any, init: any) => {
      if (String(url).includes("/api/sensor-tower/fulfill")) {
        posts.push(JSON.parse(init.body));
        return new Response(JSON.stringify({ status: "success" }), { status: 200 });
      }
      return new Response("rate limited", { status: 429 });  // ST initialize → 429
    }));
    await fulfillSensorTower({ req_id: "R4", st_tool: "t", params: {} });
    expect(posts.find((p) => p.req_id === "R4").error.kind).toBe("budget_exceeded");
  });
});
