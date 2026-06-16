import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/gaa/backend";

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || !body.req_id || (body.result === undefined && body.error === undefined)) {
    return NextResponse.json({ status: "error", error: "req_id and result|error required" }, { status: 400 });
  }
  const upstream = await fetch(`${BACKEND_URL()}/sensor-tower/fulfill`, {
    method: "POST",
    headers: { authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}`, "content-type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => null);
  if (!upstream || !upstream.ok) {
    return NextResponse.json({ status: "error", error: `backend ${upstream?.status ?? "unreachable"}` }, { status: 502 });
  }
  return NextResponse.json({ status: "success" });
}
