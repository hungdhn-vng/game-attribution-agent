import { describe, it, expect } from "vitest";
import { parseSSEChunk } from "../../lib/gaa/sse";

describe("parseSSEChunk", () => {
  it("parses complete events and buffers a partial tail", () => {
    const r1 = parseSSEChunk("",
      'data: {"type":"activity","text":"running analyze…"}\n\n' +
      'data: {"type":"thinking","text":"why","scope":"orchestration"}\n\n' +
      'data: {"type":"token","text":"par');
    expect(r1.events.map((e) => e.type)).toEqual(["activity", "thinking"]);
    expect(r1.buffer).toContain('"token"');
    const r2 = parseSSEChunk(r1.buffer, 'tial"}\n\ndata: {"type":"done","run_id":"abc"}\n\n');
    expect(r2.events.map((e) => e.type)).toEqual(["token", "done"]);
    expect(r2.events[0]).toMatchObject({ type: "token", text: "partial" });
    expect(r2.events[1]).toMatchObject({ type: "done", run_id: "abc" });
    expect(r2.buffer).toBe("");
  });

  it("tolerates an unknown event type and skips malformed json", () => {
    const r = parseSSEChunk("",
      'data: {"type":"thinking","text":"t"}\n\ndata: not-json\n\ndata: {"type":"weird"}\n\n');
    expect(r.events.map((e) => e.type)).toEqual(["thinking", "weird"]);
  });
});
