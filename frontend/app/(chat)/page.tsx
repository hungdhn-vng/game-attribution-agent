"use client";
import { useState } from "react";
import { ChatView } from "@/components/gaa/chat-view";
import { ArtifactsPane } from "@/components/gaa/artifacts-pane";
import type { Turn } from "@/components/gaa/use-gaa-chat";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const [runIds, setRunIds] = useState<string[]>([]);
  const [current, setCurrent] = useState<string | null>(null);

  const onMessages = (msgs: Turn[]) => {
    const ids = msgs
      .map((m) => m.runId)
      .filter((x): x is string => Boolean(x));
    setRunIds(ids);
    setCurrent(ids.at(-1) ?? null);
  };

  const open = Boolean(current);

  return (
    <div className="flex h-dvh w-full flex-row overflow-hidden">
      {/* ── Chat pane ──────────────────────────────────────────────────────── */}
      <div
        className={cn(
          "flex min-w-0 flex-col transition-[width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
          open ? "w-[55%]" : "w-full"
        )}
      >
        <ChatView onMessages={onMessages} />
      </div>

      {/* ── Dossier pane — slides in when a run exists ─────────────────────── */}
      <div
        className={cn(
          "h-dvh shrink-0 overflow-hidden transition-[width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
          open ? "w-[45%] border-l border-border/50" : "w-0"
        )}
      >
        {open && <ArtifactsPane runIds={runIds} current={current} />}
      </div>
    </div>
  );
}
