export type GaaEvent =
  | { type: "activity"; text: string }
  | { type: "thinking"; text: string; scope?: string }
  | { type: "token"; text: string }
  | { type: "done"; run_id: string | null; error?: string }
  | { type: string; [k: string]: unknown };

/** Split accumulated SSE text on event boundaries; keep an incomplete tail in `buffer`. */
export function parseSSEChunk(buffer: string, chunk: string): { events: GaaEvent[]; buffer: string } {
  const data = buffer + chunk;
  const parts = data.split("\n\n");
  const tail = parts.pop() ?? "";
  const events: GaaEvent[] = [];
  for (const part of parts) {
    const line = part.split("\n").find((l) => l.startsWith("data:"));
    if (!line) continue;
    const json = line.slice(5).trim();
    if (!json) continue;
    try {
      events.push(JSON.parse(json) as GaaEvent);
    } catch {
      /* skip malformed event */
    }
  }
  return { events, buffer: tail };
}

/** Read a fetch Response body as SSE, invoking onEvent per parsed event. */
export async function readSSE(resp: Response, onEvent: (e: GaaEvent) => void): Promise<void> {
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const { events, buffer: b } = parseSSEChunk(buffer, decoder.decode(value, { stream: true }));
    buffer = b;
    for (const e of events) onEvent(e);
  }
}
