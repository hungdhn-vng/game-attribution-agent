"use client";
import { useState } from "react";

type Mapping = { date_col: string; metric_cols: Record<string, string>; dim_cols: Record<string, string> };

export function UploadMapping({ file, onDone }: { file: File; onDone: (msg: string) => void }) {
  const [proposed, setProposed] = useState<Mapping | null>(null);
  const [b64, setB64] = useState<string>("");
  const [name, setName] = useState("MyGame");
  const [platform, setPlatform] = useState("roblox");
  const [genre, setGenre] = useState("casual");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function propose() {
    setBusy(true); setErr(null);
    const fd = new FormData(); fd.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body: fd }).then((x) => x.json());
    setBusy(false);
    if (r.status === "error") { setErr(r.error ?? "propose failed"); return; }
    setProposed(r.mapping as Mapping); setB64(r.csv_b64 as string);
  }

  async function confirm() {
    if (!proposed) return;
    setBusy(true); setErr(null);
    const r = await fetch("/api/invocations", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "onboard_confirm",
        args: { csv_b64: b64, mapping: JSON.stringify(proposed), name, platform, genre } }),
    }).then((x) => x.json());
    setBusy(false);
    if (r.status === "error") { setErr(r.error ?? "onboard failed"); return; }
    onDone(`Onboarded ${r.name} (${r.row_count} rows; metrics: ${(r.metrics ?? []).join(", ")})`);
  }

  return (
    <div className="border rounded p-3 space-y-2 text-sm">
      <div className="font-medium">Onboard CSV: {file.name}</div>
      {err && <div className="text-red-500">{err}</div>}
      {!proposed ? (
        <button type="button" className="border rounded px-2 py-1" disabled={busy} onClick={propose}>
          {busy ? "Analyzing…" : "Propose column mapping"}
        </button>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <label>Name <input className="border rounded px-1 w-full" value={name} onChange={(e) => setName(e.target.value)} /></label>
            <label>Platform <input className="border rounded px-1 w-full" value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
            <label>Genre <input className="border rounded px-1 w-full" value={genre} onChange={(e) => setGenre(e.target.value)} /></label>
            <label>Date col <input className="border rounded px-1 w-full" value={proposed.date_col}
              onChange={(e) => setProposed({ ...proposed, date_col: e.target.value })} /></label>
          </div>
          <div className="text-xs">metrics: {JSON.stringify(proposed.metric_cols)} · dims: {JSON.stringify(proposed.dim_cols)}</div>
          <button type="button" className="border rounded px-2 py-1" disabled={busy} onClick={confirm}>
            {busy ? "Onboarding…" : "Confirm & onboard"}
          </button>
        </>
      )}
    </div>
  );
}
