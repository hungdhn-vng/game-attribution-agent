"use client";
import { useState } from "react";

export function UploadMapping({ file, onDone }: { file: File; onDone: (msg: string) => void }) {
  const [platform, setPlatform] = useState("roblox");
  const [genre, setGenre] = useState("casual");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onboard() {
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("platform", platform);
    fd.append("genre", genre);
    const r = await fetch("/api/upload", { method: "POST", body: fd }).then((x) => x.json());
    setBusy(false);
    if (r.status === "error") {
      setErr(r.error ?? "onboard failed");
      return;
    }
    onDone(`Onboarded ${r.name} (${r.row_count} rows; metrics: ${(r.metrics ?? []).join(", ")})`);
  }

  return (
    <div className="border rounded p-3 space-y-2 text-sm">
      <div className="font-medium">Onboard CSV: {file.name}</div>
      <div className="text-xs text-muted-foreground">The game name is taken from the file name.</div>
      {err && <div className="text-red-500">{err}</div>}
      <div className="grid grid-cols-2 gap-2">
        <label>Platform <input className="border rounded px-1 w-full" value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>Genre <input className="border rounded px-1 w-full" value={genre} onChange={(e) => setGenre(e.target.value)} /></label>
      </div>
      <button type="button" className="border rounded px-2 py-1" disabled={busy} onClick={onboard}>
        {busy ? "Onboarding…" : "Upload & onboard"}
      </button>
    </div>
  );
}
