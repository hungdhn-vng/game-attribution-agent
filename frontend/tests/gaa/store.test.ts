import { describe, it, expect, beforeEach, vi } from "vitest";
import { listConversations, saveConversation, loadConversation, type Msg } from "../../lib/gaa/store";

beforeEach(() => {
  const mem: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (k in mem ? mem[k] : null),
    setItem: (k: string, v: string) => { mem[k] = String(v); },
    removeItem: (k: string) => { delete mem[k]; },
    clear: () => { for (const k of Object.keys(mem)) delete mem[k]; },
  });
});

describe("conversation store", () => {
  it("saves, lists, and loads conversations", () => {
    const msgs: Msg[] = [{ role: "user", content: "hi" }, { role: "assistant", content: "hello" }];
    saveConversation("c1", "First chat", msgs);
    expect(listConversations().map((c) => c.id)).toContain("c1");
    expect(loadConversation("c1")).toEqual(msgs);
  });
  it("returns [] for an unknown conversation", () => {
    expect(loadConversation("nope")).toEqual([]);
  });
});
