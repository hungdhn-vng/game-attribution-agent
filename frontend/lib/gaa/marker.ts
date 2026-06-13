const MARKER = /\[\[gaa:run_id=([^\]]+)\]\]/;

export function extractRunId(text: string): string | null {
  const m = text.match(MARKER);
  return m ? m[1] : null;
}

export function stripMarker(text: string): string {
  return text.replace(/\s*\[\[gaa:run_id=[^\]]+\]\]\s*/g, "").trim();
}
