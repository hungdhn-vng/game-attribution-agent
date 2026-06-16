import { BACKEND_URL } from "@/lib/gaa/backend";

/** Browser lands here after O365 login. Relay {code,state} to the agent server-to-server,
 *  then render a short page telling the user to return to chat. */
// This endpoint is the public OAuth redirect URI, so any query value reflected into the
// page must be HTML-escaped (the `error` param is attacker-controllable → XSS otherwise).
const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export async function GET(req: Request) {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const err = url.searchParams.get("error");

  const page = (title: string, body: string, ok: boolean) =>
    new Response(
      `<!doctype html><meta charset="utf-8"><title>${title}</title>` +
      `<body style="font-family:system-ui;max-width:32rem;margin:4rem auto;text-align:center">` +
      `<h2>${ok ? "✅" : "⚠️"} ${title}</h2><p>${body}</p></body>`,
      { status: ok ? 200 : 400, headers: { "content-type": "text/html; charset=utf-8" } },
    );

  if (err) return page("Sensor Tower connection failed", `O365 returned: ${esc(err)}`, false);
  if (!code || !state) return page("Sensor Tower connection failed", "Missing code/state.", false);

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL()}/sensor-tower/callback`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${process.env.GAA_AGENT_TOKEN ?? ""}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ code, state }),
    });
  } catch {
    // Backend unreachable — show the failure page rather than a raw 500 in the browser tab.
    return page("Sensor Tower connection failed",
      "Couldn't reach the agent. Please try connecting again from the chat.", false);
  }

  if (!upstream.ok) {
    return page("Sensor Tower connection failed",
      "Couldn't complete the connection. Please try connecting again from the chat.", false);
  }
  return page("Sensor Tower connected",
    "You can close this tab and return to your chat — the agent now has access.", true);
}
