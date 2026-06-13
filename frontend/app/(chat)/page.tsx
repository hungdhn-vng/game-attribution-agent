"use client";
import { useEffect, useState } from "react";
import { useGaaChat, type Turn } from "@/components/gaa/use-gaa-chat";
import { ActivityStrip } from "@/components/gaa/activity-strip";
import { ThinkingPanel } from "@/components/gaa/thinking-panel";
import { ArtifactsPane } from "@/components/gaa/artifacts-pane";
import { AdminUnlock } from "@/components/gaa/admin-unlock";
import { UploadMapping } from "@/components/gaa/upload-mapping";
import { saveConversation, loadConversation } from "@/lib/gaa/store";

const CONV = "default";

export default function ChatPage() {
  const { messages, streaming, latestRunId, send, setMessages } = useGaaChat();
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    const m = loadConversation(CONV);
    if (m.length) setMessages(m as Turn[]);
  }, [setMessages]);
  useEffect(() => {
    if (messages.length) saveConversation(CONV, messages[0]?.content ?? "chat", messages);
  }, [messages]);

  const runIds = messages.map((m) => m.runId).filter((x): x is string => Boolean(x));

  return (
    <div className="flex h-screen">
      <div className="flex flex-col w-1/2 border-r">
        <div className="flex justify-between items-center p-2 border-b"><span className="font-medium">GAA</span><AdminUnlock /></div>
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : ""}>
              {m.role === "assistant" && (<><ThinkingPanel thinking={m.thinking} /><ActivityStrip activity={m.activity} /></>)}
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
          ))}
          {file && (
            <UploadMapping file={file} onDone={(msg) => {
              setFile(null);
              setMessages((c) => [...c, { role: "assistant", content: msg }]);
            }} />
          )}
        </div>
        <form className="p-2 border-t flex gap-2"
              onSubmit={(e) => { e.preventDefault(); if (input.trim()) { send(input); setInput(""); } }}>
          <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
          <input className="flex-1 border rounded px-2" value={input} onChange={(e) => setInput(e.target.value)}
                 placeholder="Ask: why did revenue drop?" disabled={streaming} />
          <button type="submit" className="border rounded px-3" disabled={streaming}>Send</button>
        </form>
      </div>
      <div className="w-1/2"><ArtifactsPane runIds={runIds} current={latestRunId} /></div>
    </div>
  );
}
