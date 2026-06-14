import type { Msg } from "@/lib/gaa/store";

type ChatTurn = Msg & { runId?: string | null };

export type ChatRequestBody = { messages: Msg[]; active_run_id?: string };

/**
 * Build the POST body for /chat from the conversation so far.
 *
 * The backend is stateless and the run_id marker is stripped from assistant
 * content before re-sending, so the run the user is looking at is otherwise
 * invisible to follow-up turns. Carry the most recent run id out-of-band as
 * `active_run_id` so drilldowns/follow-ups reuse it instead of starting anew.
 */
export function buildChatBody(history: ChatTurn[]): ChatRequestBody {
  const messages: Msg[] = history.map((m) => ({ role: m.role, content: m.content }));
  const activeRunId = history
    .map((m) => m.runId)
    .filter((x): x is string => Boolean(x))
    .at(-1);
  return activeRunId ? { messages, active_run_id: activeRunId } : { messages };
}

/**
 * Reshape an incoming /api/chat request for the backend /chat call, preserving
 * `active_run_id`. The proxy previously forwarded only `messages`, which silently
 * dropped the active run id and defeated cross-turn run reuse.
 */
export function forwardChatBody(
  raw: { messages?: Msg[]; active_run_id?: string | null },
): ChatRequestBody {
  const messages = raw.messages ?? [];
  const activeRunId = raw.active_run_id || undefined;
  return activeRunId ? { messages, active_run_id: activeRunId } : { messages };
}
