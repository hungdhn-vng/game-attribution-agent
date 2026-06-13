"use client";
import { useState } from "react";

export function ArtifactsPane({ runIds, current }: { runIds: string[]; current: string | null }) {
  const [sel, setSel] = useState<string | null>(null);
  const [tab, setTab] = useState<"dossier" | "trace">("dossier");
  const runId = sel ?? current;
  if (!runId) return <div className="p-4 text-sm text-muted-foreground">No dossier yet — ask about a game.</div>;
  const options = [...new Set([runId, ...runIds])];
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 p-2 border-b text-sm">
        <select className="border rounded px-1" value={runId} onChange={(e) => setSel(e.target.value)}>
          {options.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button type="button" className={tab === "dossier" ? "font-medium" : "opacity-60"} onClick={() => setTab("dossier")}>Dossier</button>
        <button type="button" className={tab === "trace" ? "font-medium" : "opacity-60"} onClick={() => setTab("trace")}>Trace</button>
      </div>
      {tab === "dossier" ? (
        <iframe key={runId} title="dossier" sandbox="allow-scripts"
                src={`/api/runs/${encodeURIComponent(runId)}/report.html`} className="flex-1 w-full border-0" />
      ) : (
        <iframe key={`${runId}-trace`} title="trace" sandbox=""
                src={`/api/runs/${encodeURIComponent(runId)}/summary.md`} className="flex-1 w-full border-0" />
      )}
    </div>
  );
}
