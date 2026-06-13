# Reasoning Reveal (`thinking` SSE events) — Design

**Status:** Approved design (pre-implementation)
**Date:** 2026-06-13
**Depends on:** the deployed GAA Custom Agent backend (`2026-06-13-gaa-custom-agent-design.md`, runtime v3 ACTIVE).
**Consumed by:** the frontend (`2026-06-13-gaa-frontend-design.md` §15 — the `thinking`-event renderer). **This spec supersedes the *mechanism* §15 sketched** (it assumed vLLM `reasoning_content` streaming + a pipeline/thread restructure); the SSE **contract is unchanged**, but a feasibility spike showed a much simpler implementation.
**Scope:** backend — make `/chat` emit `thinking` SSE events carrying the agent's reasoning, in two phases (orchestration + synthesis).

---

## 1. Why this exists

Users want to see the agent *think*, not just see the final answer + activity steps. The agent already reasons — we just don't surface it. This adds a `thinking` SSE event that reveals (a) the agent's per-step tool-decision reasoning and (b) the analytical rationale behind a synthesis. The frontend shows it in a collapsible "Thinking" panel.

## 2. Spike finding (what shaped this design)

A live probe against MaaS (`google/gemma-4-31b-it`) established:
- MaaS/vLLM **does not** expose `reasoning_content` as a separate streaming field, and emits **no `<think>` tags** — `enable_thinking` on/off makes no channel difference. So capturing a separate reasoning stream is **not available** on this deployment.
- The model **reliably emits its reasoning as ordinary output**: prompted for a `thought` field, it produces a coherent 1–2 sentence rationale, and the decision JSON still parses.
- Synthesis already produces a reasoning field on the `AttributionHypothesis` (`rationale`).

**Consequence:** we reveal reasoning the model *already produces* — no streaming LLM client, no `enable_thinking`, no pipeline restructure.

## 3. Goals / non-goals

**Goals**
- `/chat` emits `thinking` SSE events: the orchestration tool-decision reasoning (Phase 1) and the synthesis rationale (Phase 2).
- A config toggle to disable it cleanly (fall back to exactly today's behavior).
- No regression to JSON-decision reliability or the verified agent loop.

**Non-goals**
- **Token-by-token** streaming of reasoning (user chose *reveal*, one event per reasoning moment — simpler, low-risk). Revisit only if the UX demands it.
- Capturing vLLM `reasoning_content` / re-enabling `enable_thinking` (spike: unavailable + costly).
- Streaming reasoning *during* `analyze` execution (Phase 2 reveals the rationale *after* analyze completes — no threading).

## 4. The SSE contract (unchanged from frontend §15)

```
data: {"type":"thinking","text":"<reasoning>","scope":"orchestration"|"synthesis"}\n\n
```
- One event per reasoning moment (not token chunks).
- `scope` labels the source: `orchestration` (per-turn tool decision) or `synthesis` (the hypothesis rationale).
- Ordering within a turn: `thinking`(orchestration) → `activity` → [for analyze: `thinking`(synthesis)] → `token`(final narration) → `done`. The frontend renders by arrival.

## 5. Config toggle

- `GAA_STREAM_REASONING` env, default **on** (`"1"`; `"0"`/`"false"` = off). Read once via a small helper (e.g. `gaa.server.persona.reasoning_enabled()` reading `os.environ`).
- **On:** the system prompt asks for a `thought` field; the loop emits `thinking` events.
- **Off:** the prompt omits the `thought` ask; the loop emits no `thinking` events — byte-for-byte today's behavior. The safety valve if reasoning ever hurts JSON reliability or latency in prod.

## 6. Phase 1 — orchestration reasoning

**`gaa/server/persona.py`** — `_PROTOCOL` (only when `reasoning_enabled()`): the decision JSON gains an optional leading `thought`:
```
{"thought": "<1–2 sentences: why this next step>", "action": "<name>", "args": { … }}
   — or —
{"thought": "<1–2 sentences>", "final": "<message>"}
```
When reasoning is off, the protocol is exactly today's (`action`/`final` only).

**`gaa/server/agent.py`** — in the loop, after `decision = self._llm.complete_json(...)` parses to a dict, **before** the action/final handling:
```python
if reasoning_enabled():
    thought = (decision or {}).get("thought")
    if isinstance(thought, str) and thought.strip():
        yield {"type": "thinking", "text": thought.strip(), "scope": "orchestration"}
```
No change to the call path (still non-streaming `complete_json`); `_extract_json` already tolerates the extra field; `action`/`final` parse unchanged. A decision lacking `thought` simply yields no event (robust).

## 7. Phase 2 — synthesis reasoning

The `AttributionHypothesis` already carries a `rationale` (and per-cause reasoning). Reveal it *after* `analyze`/`synth` completes — no streaming during the pipeline.

**`gaa/cli/main.py`** `_run_view` (and/or the synth result): when the run has a hypothesis, include its `rationale` in the returned dict, e.g. `view["rationale"] = run.state["hypothesis"].get("rationale")` (only when present). This is a small, backward-compatible addition (the field is ignored by callers that don't use it).

**`gaa/server/agent.py`** — after dispatching `analyze` or `synth` with `status == "success"`, if `reasoning_enabled()` and the result carries a `rationale`:
```python
if reasoning_enabled() and action in ("analyze", "synth"):
    rationale = result.get("rationale") if isinstance(result, dict) else None
    if isinstance(rationale, str) and rationale.strip():
        yield {"type": "thinking", "text": rationale.strip(), "scope": "synthesis"}
```
Emitted between the `activity` and the eventual `final` for that turn.

## 8. Reuse vs. new code

**Changed (no new files):**
- `gaa/server/persona.py` — protocol text + `reasoning_enabled()` helper.
- `gaa/server/agent.py` — emit `thinking` (orchestration + synthesis).
- `gaa/cli/main.py` — `_run_view` surfaces `rationale` when a hypothesis exists.

**Unchanged:** the LLM client (no streaming method), the pipeline/Synthesizer (no callback/threading), persistence, routes, auth.

## 9. Error handling / robustness

- Missing/empty `thought` or `rationale` → no event (never error).
- Reasoning off → no protocol change, no events.
- A model that ignores the `thought` ask → the decision still parses (the field is optional); we just don't reveal reasoning that turn.
- `thinking` text is plain prose; the frontend renders it as text (no markup trust issues beyond normal escaping).

## 10. Testing

- **Offline (pytest):** extend `tests/server/test_agent.py` — a `ScriptedLLM` decision dict that includes `"thought"` ⇒ assert a `{"type":"thinking","scope":"orchestration"}` event is yielded **before** the `activity`/`final`; with `GAA_STREAM_REASONING=0` ⇒ **no** thinking event; an `analyze` whose result carries a `rationale` ⇒ a `{"scope":"synthesis"}` event. Unit `reasoning_enabled()` (env parsing). `_run_view` test: hypothesis present ⇒ `rationale` in the view; absent ⇒ key omitted. The existing 296 stay green.
- **Live (re-verify):** with reasoning on, a `/chat` analysis streams `thinking`(orchestration) + `thinking`(synthesis) events and the decision JSON still parses reliably (the spike already demonstrated reliability); with `GAA_STREAM_REASONING=0`, no thinking events and behavior matches v3.

## 11. Deployment

- No new env required to keep current behavior; set `GAA_STREAM_REASONING=1` (default) to enable. Ship in the next image build + `runtime.sh update --from-cr --env-file ./.env`.
- Re-run the live verification (§10) after deploy.

## 12. Key decisions

| Decision | Alternative | Why |
|---|---|---|
| Reveal reasoning (one event/moment) | true token-by-token streaming | spike: no separate reasoning channel; reshaping the verified loop for token-streaming wasn't worth the risk (user choice) |
| Reuse the model's `thought` field + hypothesis `rationale` | capture vLLM `reasoning_content`; re-enable `enable_thinking` | spike: `reasoning_content` unavailable on this MaaS; the model already produces both fields |
| Reveal synthesis rationale *after* analyze | stream it *during* analyze | avoids the pipeline callback + threading restructure entirely |
| `GAA_STREAM_REASONING` toggle (default on) | always on | cheap escape hatch if it ever hurts JSON reliability/latency |
| Keep the SSE contract from frontend §15 | a new event shape | the frontend renderer is already specced against it; one event vs many tokens is transparent to the renderer |

## 13. Risks / open items

1. **Decision-prompt change** — asking for a `thought` field slightly alters the decision prompt; mitigated by the spike (reliable + parsable) + the toggle + a re-verify after deploy. If reliability ever regresses, `GAA_STREAM_REASONING=0`.
2. **Reasoning quality** — the revealed `thought`/`rationale` is the model's own; it may occasionally be terse or generic. Acceptable; it's a transparency feature, not a correctness gate.
3. **Future token-streaming** — if the UX later wants true token-by-token reasoning, it's a separate change (streaming LLM path + prose-before-fenced-JSON, validated by the spike) — out of scope here.
