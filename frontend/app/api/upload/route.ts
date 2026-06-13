import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/gaa/backend";

/** Receive a CSV file, base64 it, ask the backend to propose a column mapping (non-admin). */
export async function POST(req: Request) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ status: "error", error: "no file" }, { status: 400 });
  }
  const b64 = Buffer.from(await file.arrayBuffer()).toString("base64");
  const upstream = await fetch(`${BACKEND_URL()}/invocations`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}` },
    body: JSON.stringify({ action: "onboard_propose", args: { csv_b64: b64 } }),
  });
  const data = await upstream.json().catch(() => ({ status: "error", error: `backend ${upstream.status}` }));
  // echo the b64 back so the client can pass it to onboard_confirm after editing the mapping
  return NextResponse.json({ ...data, csv_b64: b64 }, { status: 200 });
}
