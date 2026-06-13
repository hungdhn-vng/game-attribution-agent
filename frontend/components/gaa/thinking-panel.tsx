"use client";
import { useState } from "react";
import type { Think } from "./use-gaa-chat";

export function ThinkingPanel({ thinking }: { thinking?: Think[] }) {
  const [open, setOpen] = useState(false);
  if (!thinking?.length) return null;
  return (
    <div className="my-1 text-sm">
      <button type="button" className="text-xs underline text-muted-foreground" onClick={() => setOpen(!open)}>
        {open ? "Hide thinking" : `Show thinking (${thinking.length})`}
      </button>
      {open && (
        <div className="mt-1 border-l-2 pl-2 space-y-1 text-muted-foreground">
          {thinking.map((t, i) => (
            <div key={i}><span className="opacity-60">[{t.scope ?? "thinking"}]</span> {t.text}</div>
          ))}
        </div>
      )}
    </div>
  );
}
