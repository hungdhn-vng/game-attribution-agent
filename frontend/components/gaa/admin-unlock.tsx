"use client";
import { useState } from "react";

export function AdminUnlock({ onChange }: { onChange?: (admin: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [pass, setPass] = useState("");
  const [admin, setAdmin] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function unlock() {
    const r = await fetch("/api/admin/unlock", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ passphrase: pass }) });
    if (r.ok) { setAdmin(true); setOpen(false); setErr(null); onChange?.(true); }
    else setErr("incorrect passphrase");
  }
  async function lock() { await fetch("/api/admin/unlock", { method: "DELETE" }); setAdmin(false); onChange?.(false); }
  return (
    <div className="text-xs">
      {admin ? (
        <button type="button" className="border rounded px-2 py-0.5" onClick={lock}>🔓 admin · lock</button>
      ) : open ? (
        <span className="space-x-1">
          <input type="password" className="border rounded px-1" placeholder="admin passphrase"
                 value={pass} onChange={(e) => setPass(e.target.value)} />
          <button type="button" className="border rounded px-2 py-0.5" onClick={unlock}>unlock</button>
          {err && <span className="text-red-500">{err}</span>}
        </span>
      ) : (
        <button type="button" className="opacity-60" onClick={() => setOpen(true)}>🔒</button>
      )}
    </div>
  );
}
