"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function ArtifactsPane({
  runIds,
  current,
}: {
  runIds: string[];
  current: string | null;
}) {
  const [sel, setSel] = useState<string | null>(null);
  const [tab, setTab] = useState<"dossier" | "trace">("dossier");

  const { resolvedTheme } = useTheme();
  const dossierRef = useRef<HTMLIFrameElement>(null);

  // Push the app's current theme into the sandboxed dossier iframe.
  const postTheme = useCallback(() => {
    dossierRef.current?.contentWindow?.postMessage(
      { type: "gaa-theme", theme: resolvedTheme === "dark" ? "dark" : "light" },
      "*"
    );
  }, [resolvedTheme]);

  // Re-post on theme change (and on mount).
  useEffect(() => {
    postTheme();
  }, [postTheme]);

  // Reply to the dossier's ready handshake (covers iframe-loads-first races).
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (
        e.source === dossierRef.current?.contentWindow &&
        e.data?.type === "gaa-theme-ready"
      ) {
        postTheme();
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [postTheme]);

  const runId = sel ?? current;

  // Deduplicated list of options — current run first, then others
  const options = runId
    ? [...new Set([runId, ...runIds])]
    : [...new Set(runIds)];

  return (
    <div className="flex h-full flex-col bg-sidebar">
      {/* ── Header bar — mirrors artifact.tsx header ───────────────────────── */}
      <div className="flex h-[calc(3.5rem+1px)] shrink-0 items-center justify-between border-b border-border/50 px-4">
        {/* Left: title + run selector */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex flex-col gap-0.5">
            <div className="text-sm font-semibold leading-tight tracking-tight">
              Dossier
            </div>
            {runId && (
              <div className="text-xs text-muted-foreground font-mono truncate max-w-[180px]">
                {runId}
              </div>
            )}
          </div>

          {/* Run switcher — only shown when there are multiple runs */}
          {options.length > 1 && (
            <Select
              value={runId ?? undefined}
              onValueChange={(v) => setSel(v)}
            >
              <SelectTrigger
                size="sm"
                className="h-7 text-xs rounded-lg border-border/50 bg-background/60 px-2"
              >
                <SelectValue placeholder="Switch run…" />
              </SelectTrigger>
              <SelectContent>
                {options.map((r) => (
                  <SelectItem key={r} value={r} className="text-xs font-mono">
                    {r}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Right: Dossier / Trace tab buttons */}
        {runId && (
          <div className="flex items-center gap-1 rounded-lg border border-border/50 bg-muted/40 p-0.5">
            {(["dossier", "trace"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs capitalize transition-colors",
                  tab === t
                    ? "bg-background text-foreground font-medium shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Content area ───────────────────────────────────────────────────── */}
      {!runId ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-muted-foreground">
            Run an analysis to see the dossier
          </p>
        </div>
      ) : tab === "dossier" ? (
        <iframe
          key={runId}
          ref={dossierRef}
          title="dossier"
          sandbox="allow-scripts"
          src={`/api/runs/${encodeURIComponent(runId)}/report.html`}
          onLoad={() => postTheme()}
          className="flex-1 w-full border-0 bg-background"
        />
      ) : (
        <iframe
          key={`${runId}-trace`}
          title="trace"
          sandbox=""
          src={`/api/runs/${encodeURIComponent(runId)}/summary.md`}
          className="flex-1 w-full border-0 bg-background"
        />
      )}
    </div>
  );
}
