// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { listConversations, saveConversation, loadConversation, type Msg } from "../../lib/gaa/store";

beforeEach(() => localStorage.clear());

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
