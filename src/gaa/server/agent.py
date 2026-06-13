"""The /chat agent loop — a full clone of the OpenClaw agent, in-process.

Stateless: the caller passes the full messages[]. Each turn we ask the model for ONE
decision JSON ({"action":...}|{"final":...}), dispatch actions in-process (byte-exact
results, no garbling), and stream SSE events. Bounded by max_iters. The most recent
run_id touched is appended to the final answer as a [[gaa:run_id=...]] marker so the
frontend can fetch + render the dossier.
"""
from __future__ import annotations

import json
from typing import Iterator

from gaa.server import actions, persona
from gaa import persist


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "user")
        lines.append(f"{role.upper()}: {m.get('content', '')}")
    return "\n".join(lines)


def _chunk(text: str, size: int = 60) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i:i + size]


class ChatAgent:
    def __init__(self, ctx, llm, *, max_iters: int = 8) -> None:
        self._ctx = ctx
        self._llm = llm
        self._max_iters = max_iters

    def run(self, messages: list[dict], *, is_admin: bool = False) -> Iterator[dict]:
        """Yield SSE event dicts: {"type":"activity"|"token"|"done", ...}."""
        ctx = self._ctx
        system = persona.assemble_system_prompt(ctx, admin=is_admin)
        convo = _format_messages(messages)
        last_run_id = None

        for _ in range(self._max_iters):
            decision = self._llm.complete_json(system, convo)
            if isinstance(decision, dict) and "final" in decision:
                text = str(decision["final"])
                if last_run_id:
                    text += f"\n\n[[gaa:run_id={last_run_id}]]"
                for piece in _chunk(text):
                    yield {"type": "token", "text": piece}
                yield {"type": "done", "run_id": last_run_id}
                return

            action = (decision or {}).get("action")
            a_args = (decision or {}).get("args", {}) or {}
            if not action:
                yield {"type": "token", "text": "(no action or final produced)"}
                yield {"type": "done", "run_id": last_run_id}
                return

            yield {"type": "activity", "text": f"running {action}…"}
            result = actions.dispatch(ctx, action, a_args, is_admin=is_admin)
            if isinstance(result, dict) and result.get("run_id"):
                last_run_id = result["run_id"]
            if (action in actions.MUTATING_ACTIONS
                    and isinstance(result, dict) and result.get("status") == "success"):
                try:
                    persist.snapshot(ctx)
                except Exception:
                    pass  # persistence is best-effort; never break the chat
            convo += f"\nTOOL[{action}] -> {json.dumps(result)[:4000]}"

        # max iterations reached without a final
        yield {"type": "token", "text": "(stopped: reached the tool-iteration limit)"}
        yield {"type": "done", "run_id": last_run_id}
