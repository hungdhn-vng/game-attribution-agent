import { describe, it, expect } from "vitest";
import { buildChatBody, forwardChatBody } from "../../lib/gaa/request";

describe("buildChatBody", () => {
  it("carries the latest run id as active_run_id so follow-ups reuse the run", () => {
    const body = buildChatBody([
      { role: "user", content: "why did dau drop?" },
      { role: "assistant", content: "DAU fell in SEA.", runId: "run-1" },
      { role: "user", content: "analyze the market trends" },
    ]);
    expect(body.active_run_id).toBe("run-1");
    expect(body.messages).toEqual([
      { role: "user", content: "why did dau drop?" },
      { role: "assistant", content: "DAU fell in SEA." },
      { role: "user", content: "analyze the market trends" },
    ]);
  });

  it("uses the most recent non-null run id when several turns produced runs", () => {
    const body = buildChatBody([
      { role: "assistant", content: "a", runId: "run-1" },
      { role: "assistant", content: "b", runId: "run-2" },
      { role: "assistant", content: "c", runId: null },
    ]);
    expect(body.active_run_id).toBe("run-2");
  });

  it("omits active_run_id when no turn has produced a run yet", () => {
    const body = buildChatBody([{ role: "user", content: "hi" }]);
    expect(body.active_run_id).toBeUndefined();
    expect(body.messages).toEqual([{ role: "user", content: "hi" }]);
  });
});

describe("forwardChatBody (proxy → backend)", () => {
  it("forwards active_run_id from the client request to the backend", () => {
    const out = forwardChatBody({
      messages: [{ role: "user", content: "market trends?" }],
      active_run_id: "run-1",
    });
    expect(out).toEqual({
      messages: [{ role: "user", content: "market trends?" }],
      active_run_id: "run-1",
    });
  });

  it("omits active_run_id when the client did not send one, and defaults messages", () => {
    expect(forwardChatBody({})).toEqual({ messages: [] });
    expect(forwardChatBody({ active_run_id: null, messages: [{ role: "user", content: "x" }] }))
      .toEqual({ messages: [{ role: "user", content: "x" }] });
  });
});
