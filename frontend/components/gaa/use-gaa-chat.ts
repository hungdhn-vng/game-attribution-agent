"use client";
import { useCallback, useRef, useState } from "react";
import { readSSE } from "@/lib/gaa/sse";
import { extractRunId, stripMarker } from "@/lib/gaa/marker";
import { buildChatBody } from "@/lib/gaa/request";
import type { Msg } from "@/lib/gaa/store";

export type Think = { scope?: string; text: string };
export type Turn = Msg & { thinking?: Think[]; activity?: string[]; runId?: string | null };

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
        }
      });
    } finally {
      setStreaming(false);
    }
  }, []);

  return { messages, streaming, latestRunId, send, setMessages };
}
