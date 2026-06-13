import { BACKEND_URL } from "@/lib/gaa/backend";

const ARTIFACTS = new Set(["report.html", "summary.md", "activity.log", "ledger.jsonl", "job.json"]);
const TYPES: Record<string, string> = {
  "report.html": "text/html", "summary.md": "text/markdown",
  "activity.log": "text/plain", "ledger.jsonl": "application/x-ndjson", "job.json": "application/json",
};

export async function GET(_req: Request, ctx: { params: Promise<{ id: string; artifact: string }> }) {
  const { id, artifact } = await ctx.params;
  if (!ARTIFACTS.has(artifact) || !/^[A-Za-z0-9._-]+$/.test(id)) {
    return new Response("not found", { status: 404 });
  }
  const upstream = await fetch(`${BACKEND_URL()}/runs/${encodeURIComponent(id)}/${artifact}`);
  if (!upstream.ok || !upstream.body) return new Response("not found", { status: 404 });
  return new Response(upstream.body, {
    headers: { "content-type": TYPES[artifact], "cache-control": "no-store" },
  });
}
