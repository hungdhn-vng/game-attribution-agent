"use client";
import { useEffect, useState } from "react";
import { MessageResponse } from "@/components/ai-elements/message";

type State =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; markdown: string };

/**
 * Renders a run's `summary.md` natively in-app via the same Streamdown
 * renderer the chat uses — themed, selectable, properly typeset. Replaces the
 * old iframe that dumped raw markdown as unstyled plain text.
 */
export function TracePanel({ runId }: { runId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ status: "loading" });
    fetch(`/api/runs/${encodeURIComponent(runId)}/summary.md`, {
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error("not found"))))
      .then((markdown) => setState({ status: "ready", markdown }))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          setState({ status: "error" });
        }
      });
    return () => ctrl.abort();
  }, [runId]);

  if (state.status === "loading") {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading trace…</p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Couldn’t load the trace.</p>
      </div>
    );
  }

  if (!state.markdown.trim()) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">No summary yet.</p>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-background px-5 py-4">
      <MessageResponse>{state.markdown}</MessageResponse>
    </div>
  );
}
