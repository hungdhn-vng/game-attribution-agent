"use client";
import { useCallback, useRef, useState } from "react";
import { readSSE } from "@/lib/gaa/sse";
import { extractRunId, stripMarker } from "@/lib/gaa/marker";
import { buildChatBody } from "@/lib/gaa/request";
import type { Msg } from "@/lib/gaa/store";
import { getToken, tokenIsFresh } from "@/lib/gaa/st-oauth";
import { callSensorTower } from "@/lib/gaa/st-client";

export type Think = { scope?: string; text: string };
export type Turn = Msg & { thinking?: Think[]; activity?: string[]; runId?: string | null };

export async function fulfillSensorTower(ev: { req_id: string; st_tool: string; params: Record<string, unknown> }) {
  const post = (body: unknown) =>
    fetch("/api/sensor-tower/fulfill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const token = getToken();
  if (!tokenIsFresh(token, Math.floor(Date.now() / 1000))) {
    await post({ req_id: ev.req_id, error: { kind: "not_connected" } });
    return;
  }
  try {
    const data = await callSensorTower(token!, ev);
    await post({ req_id: ev.req_id, result: data });
  } catch (e) {
    const detail = (e as Error).message;
    // ST 429 = shared monthly data-point budget exhausted; surface it distinctly so the agent
    // can tell the user (vs a generic upstream error). st-client throws "ST <method> 429".
    const kind = /\b429\b/.test(detail) ? "budget_exceeded" : "upstream_error";
    await post({ req_id: ev.req_id, error: { kind, detail } });
  }
}

export function useGaaChat(initial: Turn[] = []) {
  const [messages, setMessages] = useState<Turn[]>(initial);
  const [streaming, setStreaming] = useState(false);
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  const msgsRef = useRef(messages);
  msgsRef.current = messages;

  const send = useCallback(async (text: string) => {
    const history: Turn[] = [...msgsRef.current, { role: "user", content: text }];
    const assistant: Turn = { role: "assistant", content: "", thinking: [], activity: [] };
    setMessages([...history, assistant]);
    setStreaming(true);
    const body = buildChatBody(history);
    let acc = "";
    const patch = (fn: (a: Turn) => void) =>
      setMessages((cur) => {
        const c = [...cur];
        const a = { ...c[c.length - 1] };
        fn(a);
        c[c.length - 1] = a;
        return c;
      });
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      await readSSE(resp, (e) => {
        if (e.type === "activity") {
          const ev = e as { type: "activity"; text: string };
          patch((a) => { a.activity = [...(a.activity ?? []), ev.text]; });
        } else if (e.type === "thinking") {
          const ev = e as { type: "thinking"; text: string; scope?: string };
          patch((a) => { a.thinking = [...(a.thinking ?? []), { scope: ev.scope, text: ev.text }]; });
        } else if (e.type === "token") {
          const ev = e as { type: "token"; text: string };
          acc += ev.text;
          patch((a) => { a.content = stripMarker(acc); });
        } else if (e.type === "done") {
          const ev = e as { type: "done"; run_id?: string | null };
          const rid = ev.run_id ?? extractRunId(acc);
          patch((a) => { a.runId = rid ?? null; a.content = stripMarker(acc); });
          if (rid) setLatestRunId(rid);
        } else if (e.type === "st_request") {
          // Fire-and-forget; swallow a failed fulfill POST (the agent's relay just times out).
          void fulfillSensorTower(e as { req_id: string; st_tool: string; params: Record<string, unknown> }).catch(() => {});
        }
      });
    } finally {
      setStreaming(false);
    }
  }, []);

  return { messages, streaming, latestRunId, send, setMessages };
}
