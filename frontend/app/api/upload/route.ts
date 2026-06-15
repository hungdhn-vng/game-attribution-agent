import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/gaa/backend";

/** Forward a CSV upload to the backend's /upload (one-shot onboard: propose + confirm). */
export async function POST(req: Request) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ status: "error", error: "no file" }, { status: 400 });
  }
  const out = new FormData();
  out.append("file", file, file.name);
  for (const k of ["platform", "genre", "adapter"]) {
    const v = form.get(k);
    if (typeof v === "string" && v) out.append(k, v);
  }
  const upstream = await fetch(`${BACKEND_URL()}/upload`, {
    method: "POST",
    headers: { authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}` },
    body: out,
  });
  const data = await upstream.json().catch(() => ({ status: "error", error: `backend ${upstream.status}` }));
  return NextResponse.json(data, { status: upstream.status === 401 ? 401 : 200 });
}
