import { cookies } from "next/headers";
import { BACKEND_URL, authHeaders } from "@/lib/gaa/backend";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({ messages: [] }));
  const adminCookie = (await cookies()).get("gaa_admin")?.value;
  const upstream = await fetch(`${BACKEND_URL()}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders(adminCookie) },
    body: JSON.stringify({ messages: body.messages ?? [] }),
  });
  if (!upstream.ok || !upstream.body) {
    return new Response(
      `data: ${JSON.stringify({ type: "done", run_id: null, error: `backend ${upstream.status}` })}\n\n`,
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  }
  return new Response(upstream.body, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" },
  });
}
