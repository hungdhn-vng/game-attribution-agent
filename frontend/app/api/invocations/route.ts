import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { BACKEND_URL, isAdmin } from "@/lib/gaa/backend";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const adminCookie = (await cookies()).get("gaa_admin")?.value;
  const payload: Record<string, unknown> = { action: body.action, args: body.args ?? {} };
  if (isAdmin(adminCookie)) payload.admin_key = process.env.GAA_ADMIN_KEY ?? "";
  const upstream = await fetch(`${BACKEND_URL()}/invocations`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}` },
    body: JSON.stringify(payload),
  });
  const data = await upstream.json().catch(() => ({ status: "error", error: `backend ${upstream.status}` }));
  return NextResponse.json(data, { status: upstream.status === 401 ? 401 : 200 });
}
