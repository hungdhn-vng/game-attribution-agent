# Backend: Reasoning Reveal + Upload-Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two small backend capabilities to the deployed GAA Custom Agent: (A) reveal the agent's reasoning as `thinking` SSE events (orchestration `thought` + synthesis `rationale`), toggled by `GAA_STREAM_REASONING`; and (B) accept base64 CSV content for onboarding and make onboarding non-admin — so the frontend's upload→analyze flow works for normal users.

**Architecture:** All changes are confined to `gaa/server/{persona,agent}.py`, `gaa/cli/main.py`, `gaa/cli/commands/{onboarding,primitives}.py`, and `gaa/server/actions.py`. No new files, no streaming LLM client, no pipeline/thread changes. Reasoning is *revealed* (one event per moment), not token-streamed — a feasibility spike proved MaaS exposes no `reasoning_content`, but the model reliably emits a `thought` field and synthesis already produces a `rationale`.

**Tech Stack:** Python 3.11, the existing `gaa` package, pytest. Env via `uv`/`.venv` — run tests with `.venv/bin/python -m pytest`.

**Specs:** `docs/superpowers/specs/2026-06-13-reasoning-streaming-design.md` (A) + `docs/superpowers/specs/2026-06-13-gaa-frontend-design.md` §7 (B).

**Baseline:** 296 tests pass on `main`.

**Reuse map (exact current code):**
- `persona.assemble_system_prompt(ctx, *, admin)` builds `parts = [soul, "## MEMORY\n"+memory?, _REDLINES, _PROTOCOL, _ANALYSIS_TOOLS] (+ _ADMIN_TOOLS if admin)`; `persona.py` already `import os`.
- `agent.ChatAgent.run(messages, *, is_admin)` is a generator; it does `from gaa.server import actions, persona`; the loop gets `decision = self._llm.complete_json(system, convo)` then handles `final`/`action`; dispatches via `actions.dispatch`; yields `{"type":"activity"|"token"|"done",…}`.
- `cli/main.py:_run_view(ctx, run)` returns `{status, run_id, stage, done, activity, ledger_count, report_path?, summary_path?, error?}`; the run's hypothesis (when present) is at `run.state["hypothesis"]` (a dict including `"rationale"`).
- `cli/commands/onboarding.py:cmd_onboard_propose` reads `pd.read_csv(args.csv, nrows=20)`; `cmd_onboard_confirm` reads `pd.read_csv(args.csv)`, loads via `_adapter(args.adapter).load(raw, mapping)`, saves metrics+profile.
- `cli/commands/primitives.py:cmd_synth` returns `{status, run_id, main_story, confidence}` and has `hyp` (an `AttributionHypothesis`, which has `.rationale: str`) in scope.
- `actions.ADMIN_ACTIONS = {"config_set","onboard_confirm","profile_use","tools_promote","tools_run","tools_remove","tools_import"}`; `actions.MUTATING_ACTIONS = {"onboard_confirm","config_set","profile_use","tools_promote","tools_remove","tools_import"}`. `_Args.__getattr__` returns `None` for missing attrs.

---

## Task 1: `reasoning_enabled()` toggle helper

**Files:**
- Modify: `src/gaa/server/persona.py`
- Test: `tests/server/test_persona.py`

- [ ] **Step 1: Write the failing test** — append to `tests/server/test_persona.py`:
```python
def test_reasoning_enabled_default_on(monkeypatch):
    monkeypatch.delenv("GAA_STREAM_REASONING", raising=False)
    assert persona.reasoning_enabled() is True


def test_reasoning_enabled_off_values(monkeypatch):
    for v in ("0", "false", "False", "no", "off"):
        monkeypatch.setenv("GAA_STREAM_REASONING", v)
        assert persona.reasoning_enabled() is False
    monkeypatch.setenv("GAA_STREAM_REASONING", "1")
    assert persona.reasoning_enabled() is True
```

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_persona.py -k reasoning -v` → FAIL (`AttributeError: module 'gaa.server.persona' has no attribute 'reasoning_enabled'`).

- [ ] **Step 3: Implement** — in `src/gaa/server/persona.py`, add after the `_ADMIN_TOOLS` constant (before `persona_dir`):
```python
def reasoning_enabled() -> bool:
    """Whether /chat reveals the agent's reasoning as `thinking` SSE events.

    Default ON. Set GAA_STREAM_REASONING to 0/false/no/off to disable (falls back to
    exactly the prior behavior — no `thought` asked for, no thinking events emitted).
    """
    return os.environ.get("GAA_STREAM_REASONING", "1").strip().lower() not in (
        "0", "false", "no", "off")
```

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_persona.py -k reasoning -v` → PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/server/persona.py tests/server/test_persona.py
git commit -m "feat(server): GAA_STREAM_REASONING toggle (persona.reasoning_enabled)"
```

---

## Task 2: persona protocol asks for an optional `thought` when reasoning is on

**Files:**
- Modify: `src/gaa/server/persona.py`
- Test: `tests/server/test_persona.py`

- [ ] **Step 1: Write the failing test** — append to `tests/server/test_persona.py`:
```python
def test_system_prompt_thought_hint_gated_by_toggle(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    monkeypatch.setenv("GAA_STREAM_REASONING", "1")
    on = persona.assemble_system_prompt(ctx, admin=False)
    monkeypatch.setenv("GAA_STREAM_REASONING", "0")
    off = persona.assemble_system_prompt(ctx, admin=False)
    assert '"thought"' in on          # the thought hint is present when reasoning is on
    assert '"thought"' not in off     # and absent when off
    assert '"action"' in on and '"action"' in off  # base protocol always present
```
(The `_ctx` helper already exists at the top of this test file.)

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_persona.py -k thought_hint -v` → FAIL (`"thought"` not in `on`).

- [ ] **Step 3: Implement** — in `src/gaa/server/persona.py`:
  (a) add a new constant after `_PROTOCOL`:
```python
_THOUGHT_HINT = """\
THINKING: Include a "thought" field (1-2 sentences explaining your reasoning for this
step) alongside your decision, e.g. {"thought": "…", "action": "…", "args": {…}} or
{"thought": "…", "final": "…"}. The thought is shown to the user as your reasoning; it
does not replace the action/final.
"""
```
  (b) change the `parts` assembly inside `assemble_system_prompt` from:
```python
    parts += [_REDLINES, _PROTOCOL, _ANALYSIS_TOOLS]
    if admin:
        parts.append(_ADMIN_TOOLS)
```
to:
```python
    parts += [_REDLINES, _PROTOCOL]
    if reasoning_enabled():
        parts.append(_THOUGHT_HINT)
    parts.append(_ANALYSIS_TOOLS)
    if admin:
        parts.append(_ADMIN_TOOLS)
```

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_persona.py -v` → PASS (all persona tests, incl. the existing ones).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/server/persona.py tests/server/test_persona.py
git commit -m "feat(server): system prompt asks for an optional thought field when reasoning is on"
```

---

## Task 3: agent emits orchestration `thinking` from the `thought` field

**Files:**
- Modify: `src/gaa/server/agent.py`
- Test: `tests/server/test_agent.py`

- [ ] **Step 1: Write the failing test** — append to `tests/server/test_agent.py`:
```python
def test_orchestration_thinking_emitted(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_STREAM_REASONING", "1")
    ctx = _ctx(tmp_path, monkeypatch, {})
    llm = ScriptedLLM([{"thought": "I should greet the user.", "final": "Hello!"}])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "hi"}])
    thinks = [e for e in events if e["type"] == "thinking"]
    assert thinks and thinks[0]["scope"] == "orchestration"
    assert "greet the user" in thinks[0]["text"]
    # thinking precedes the token/done for that turn
    assert events.index(thinks[0]) < next(i for i, e in enumerate(events) if e["type"] == "done")


def test_no_thinking_when_toggle_off(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_STREAM_REASONING", "0")
    ctx = _ctx(tmp_path, monkeypatch, {})
    llm = ScriptedLLM([{"thought": "secret reasoning", "final": "Hi."}])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "hi"}])
    assert not [e for e in events if e["type"] == "thinking"]
```
(`_ctx`, `_collect`, `ScriptedLLM`, `ChatAgent` already exist at the top of this test file.)

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_agent.py -k thinking -v` → FAIL (no `thinking` events).

- [ ] **Step 3: Implement** — in `src/gaa/server/agent.py`, inside `run`, immediately **after** the `try/except` that obtains `decision` and **before** `if isinstance(decision, dict) and "final" in decision:`, insert:
```python
            if persona.reasoning_enabled() and isinstance(decision, dict):
                thought = decision.get("thought")
                if isinstance(thought, str) and thought.strip():
                    yield {"type": "thinking", "text": thought.strip(), "scope": "orchestration"}
```
(`persona` is already imported. No other change.)

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_agent.py -v` → PASS (existing agent tests + 2 new).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/server/agent.py tests/server/test_agent.py
git commit -m "feat(server): agent emits orchestration thinking from the decision's thought field"
```

---

## Task 4: surface the synthesis `rationale` in run results

**Files:**
- Modify: `src/gaa/cli/main.py` (`_run_view`)
- Modify: `src/gaa/cli/commands/primitives.py` (`cmd_synth` return)
- Test: `tests/server/test_rationale.py` (new)

- [ ] **Step 1: Write the failing test** — create `tests/server/test_rationale.py`:
```python
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.cli.main import _run_view
from gaa.runs.models import Run


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_run_view_surfaces_rationale_when_present(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    run = Run(run_id="r1", session="s", query="why?")
    run.status = "done"
    run.state["hypothesis"] = {"main_story": "x", "rationale": "SEA drove the drop."}
    assert _run_view(ctx, run)["rationale"] == "SEA drove the drop."


def test_run_view_omits_rationale_when_absent(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    run = Run(run_id="r2", session="s", query="why?")
    run.status = "running"
    assert "rationale" not in _run_view(ctx, run)
```

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_rationale.py -v` → FAIL (KeyError / `"rationale"` not in view).

- [ ] **Step 3: Implement**
  (a) In `src/gaa/cli/main.py:_run_view`, immediately **before** `return view`, add:
```python
    hyp = run.state.get("hypothesis")
    if isinstance(hyp, dict) and hyp.get("rationale"):
        view["rationale"] = hyp["rationale"]
```
  (b) In `src/gaa/cli/commands/primitives.py:cmd_synth`, change the success return to include the rationale:
```python
    return {
        "status": "success",
        "run_id": args.run,
        "main_story": hyp.main_story,
        "rationale": hyp.rationale,
        "confidence": {"likelihood": hyp.confidence.likelihood,
                       "evidence_quality": hyp.confidence.evidence_quality},
    }
```

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_rationale.py -v` → PASS (2 tests).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/cli/main.py src/gaa/cli/commands/primitives.py tests/server/test_rationale.py
git commit -m "feat(server): surface hypothesis rationale in analyze/synth results"
```

---

## Task 5: agent emits synthesis `thinking` after analyze/synth

**Files:**
- Modify: `src/gaa/server/agent.py`
- Test: `tests/server/test_agent.py`

- [ ] **Step 1: Write the failing test** — append to `tests/server/test_agent.py`:
```python
def test_synthesis_thinking_after_analyze(tmp_path, monkeypatch):
    import json as _json, pandas as _pd
    monkeypatch.setenv("GAA_STREAM_REASONING", "1")
    _SYNTH = {"main_story": "DAU fell.", "rationale": "The SEA region drove the decline.",
              "causes": {"internal": [], "market": []}, "scenarios": [], "risks": [],
              "assumptions_and_gaps": []}
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    csv = tmp_path / "m.csv"
    _pd.DataFrame({"day": ["2026-05-01", "2026-05-03"], "region": ["SEA", "SEA"],
                   "dau": [1000, 400]}).to_csv(csv, index=False)
    actions.dispatch(ctx, "onboard_confirm",
                     {"csv": str(csv), "mapping": _json.dumps(
                         {"date_col": "day", "metric_cols": {"dau": "dau"},
                          "dim_cols": {"region": "region"}}),
                      "name": "G", "platform": "roblox", "genre": "survival"}, is_admin=True)
    llm = ScriptedLLM([
        {"thought": "Let me analyze.", "action": "analyze",
         "args": {"query": "why did dau drop?", "budget": "600"}},
        {"final": "Done."},
    ])
    events = _collect(ChatAgent(ctx, llm), [{"role": "user", "content": "why did dau drop?"}])
    synth = [e for e in events if e["type"] == "thinking" and e.get("scope") == "synthesis"]
    assert synth and "SEA region drove" in synth[0]["text"]
```

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_agent.py -k synthesis_thinking -v` → FAIL (no synthesis thinking event).

- [ ] **Step 3: Implement** — in `src/gaa/server/agent.py`, inside `run`, **after** the `persist.snapshot` block and **before** `convo += f"\nTOOL[{action}] -> …"`, insert:
```python
            if (persona.reasoning_enabled() and action in ("analyze", "synth")
                    and isinstance(result, dict) and result.get("status") == "success"):
                rationale = result.get("rationale")
                if isinstance(rationale, str) and rationale.strip():
                    yield {"type": "thinking", "text": rationale.strip(), "scope": "synthesis"}
```

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_agent.py -v` → PASS.

- [ ] **Step 5: Commit**
```bash
git add src/gaa/server/agent.py tests/server/test_agent.py
git commit -m "feat(server): agent emits synthesis thinking (hypothesis rationale) after analyze/synth"
```

---

## Task 6: accept base64 CSV content for onboarding

**Files:**
- Modify: `src/gaa/cli/commands/onboarding.py`
- Test: `tests/server/test_onboard_upload.py` (new)

- [ ] **Step 1: Write the failing test** — create `tests/server/test_onboard_upload.py`:
```python
import base64, json
import pandas as pd
from types import SimpleNamespace
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.cli.commands.onboarding import cmd_onboard_propose, cmd_onboard_confirm

_MAPPING = {"date_col": "day", "metric_cols": {"dau": "dau"}, "dim_cols": {"region": "region"}}
_CSV = "day,region,dau\n2026-05-01,SEA,1000\n2026-05-03,SEA,400\n"
_B64 = base64.b64encode(_CSV.encode()).decode()


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def test_propose_accepts_csv_b64(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _MAPPING)  # FakeLLM returns the mapping for profiler.propose
    args = SimpleNamespace(csv=None, csv_b64=_B64, adapter="generic")
    r = cmd_onboard_propose(ctx, args)
    assert r["status"] == "success" and "mapping" in r


def test_confirm_accepts_csv_b64(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    args = SimpleNamespace(csv=None, csv_b64=_B64, mapping=json.dumps(_MAPPING),
                           name="G", platform="roblox", genre="survival", adapter="generic")
    r = cmd_onboard_confirm(ctx, args)
    assert r["status"] == "success" and r["row_count"] == 2 and "dau" in r["metrics"]
```

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_onboard_upload.py -v` → FAIL (`csv_b64` ignored → tries to read `None` path → error status).

- [ ] **Step 3: Implement** — in `src/gaa/cli/commands/onboarding.py`:
  (a) add imports at the top (next to `import json`):
```python
import base64
import io
```
  (b) add a helper after `_adapter`:
```python
def _read_csv(args, **kw):
    """Read the onboarding CSV from base64 content (csv_b64) or a file path (csv)."""
    b64 = getattr(args, "csv_b64", None)
    if b64:
        return pd.read_csv(io.BytesIO(base64.b64decode(b64)), **kw)
    return pd.read_csv(args.csv, **kw)
```
  (c) in `cmd_onboard_propose`, replace `sample = pd.read_csv(args.csv, nrows=20)` with:
```python
        sample = _read_csv(args, nrows=20)
```
  (d) in `cmd_onboard_confirm`, replace `raw = pd.read_csv(args.csv)` with:
```python
        raw = _read_csv(args)
```

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_onboard_upload.py -v` → PASS (2 tests). Also confirm path-based onboarding still works: `.venv/bin/python -m pytest tests/ -k onboard -v` → all pass.

- [ ] **Step 5: Commit**
```bash
git add src/gaa/cli/commands/onboarding.py tests/server/test_onboard_upload.py
git commit -m "feat(server): onboarding accepts base64 CSV content (csv_b64) for browser upload"
```

---

## Task 7: make onboarding non-admin

**Files:**
- Modify: `src/gaa/server/actions.py`
- Test: `tests/server/test_actions.py`

- [ ] **Step 1: Write the failing test** — append to `tests/server/test_actions.py`:
```python
def test_onboarding_is_non_admin_exec_still_admin(tmp_path, monkeypatch):
    import base64
    from gaa.server import capabilities  # noqa: F401 (registers exec)
    ctx = _ctx(tmp_path, monkeypatch, _SYNTH)
    csv_b64 = base64.b64encode(b"day,region,dau\n2026-05-01,SEA,1000\n2026-05-03,SEA,400\n").decode()
    # onboarding works WITHOUT admin
    r = actions.dispatch(ctx, "onboard_confirm",
                         {"csv_b64": csv_b64, "mapping": json.dumps(_MAPPING), "name": "G",
                          "platform": "roblox", "genre": "survival"}, is_admin=False)
    assert r["status"] == "success"
    assert "onboard_confirm" not in actions.ADMIN_ACTIONS
    assert "onboard_confirm" in actions.MUTATING_ACTIONS   # still snapshots
    # exec is STILL admin-gated
    assert "exec" in actions.ADMIN_ACTIONS
    assert actions.dispatch(ctx, "exec", {"command": "echo x"}, is_admin=False)["status"] == "error"
```
(`_ctx`, `_SYNTH`, `_MAPPING`, `json`, `actions` already exist at the top of this test file.)

- [ ] **Step 2: Run → fail** — `.venv/bin/python -m pytest tests/server/test_actions.py -k non_admin -v` → FAIL (onboard_confirm refused without admin → `status == "error"`, and `"onboard_confirm" in ADMIN_ACTIONS`).

- [ ] **Step 3: Implement** — in `src/gaa/server/actions.py`, change the `ADMIN_ACTIONS` set to drop `onboard_confirm` (leave `MUTATING_ACTIONS` unchanged):
```python
ADMIN_ACTIONS = {
    "config_set", "profile_use", "tools_promote", "tools_run",
    "tools_remove", "tools_import",
}
```
(Update the accompanying comment to note onboarding is intentionally non-admin so the agent token alone authorizes upload→onboard; `exec`/`browse`/`self_edit` are added admin by `capabilities.register`.)

- [ ] **Step 4: Run → pass** — `.venv/bin/python -m pytest tests/server/test_actions.py -v` → PASS. Then the full suite: `.venv/bin/python -m pytest -q` → all pass (296 baseline + the new tests from Tasks 1–7; expect ~306).

- [ ] **Step 5: Commit**
```bash
git add src/gaa/server/actions.py tests/server/test_actions.py
git commit -m "feat(server): onboarding is non-admin (agent token authorizes upload->onboard); exec/etc stay admin"
```

---

## Task 8: deploy + live verification

**Files:** none (operational). Optional: add `GAA_STREAM_REASONING=1` to `.env` (default is already on; explicit is clearer).

- [ ] **Step 1: Merge to main** (if built on a branch) and confirm green
```bash
.venv/bin/python -m pytest -q   # all pass
```

- [ ] **Step 2: Rebuild + push the image** (managed CR; same pattern as the prior deploy)
```bash
SK=/Users/lap16006/.claude/skills/agentbase/scripts
TAG="v$(date +%Y%m%d%H%M%S)"; IMAGE="vcr.vngcloud.vn/111480-abp111723/gaa-custom-agent:${TAG}"
bash "$SK/cr.sh" credentials docker-login
docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

- [ ] **Step 3: Update the runtime** (env-only + new image; the runtime id is in `.agentbase/gaa_custom_agent.json`)
```bash
RID=$(python3 -c "import json;print(json.load(open('.agentbase/gaa_custom_agent.json'))['runtimeId'])")
bash "$SK/runtime.sh" update "$RID" --image "$IMAGE" --flavor runtime-s2-general-2x4 \
  --env-file ./.env --from-cr --network-mode PUBLIC
```
Poll to ACTIVE (reuse the poll loop from the prior deploy); `curl -fsS <endpoint>/health` → `{"status":"ok"}`.

- [ ] **Step 4: Live verify — thinking events + non-admin onboarding**
Run (sourcing `.env` for the token; do not print secrets):
1. **Reasoning:** `POST /chat` (Bearer token) "why did revenue drop for SampleGame?" → the SSE stream now contains `{"type":"thinking","scope":"orchestration"}` and `{"type":"thinking","scope":"synthesis"}` events, the decision JSON still parses, and a dossier is produced. Then set `GAA_STREAM_REASONING=0` (env update + redeploy) only if you want to confirm the off-path — otherwise leave it on.
2. **Non-admin onboarding:** `POST /invocations` `onboard_confirm` with a `csv_b64` payload and **no `admin_key`** → `{"status":"success"}` (proves onboarding is reachable with the agent token alone). `POST /invocations` `exec` with no `admin_key` → `{"status":"error", … admin …}` (proves dangerous tools stay gated).

- [ ] **Step 5: Update the deploy record + commit any notes**
```bash
# bump version + note in .agentbase/gaa_custom_agent.json (gitignored), then:
git add docs/superpowers/specs/2026-06-13-reasoning-streaming-design.md
git commit -m "docs: reasoning-reveal + non-admin onboarding deployed + live-verified" --allow-empty
```

---

## Self-Review

**Spec coverage (A — reasoning):**
- `GAA_STREAM_REASONING` toggle → Task 1. ✓
- protocol asks for `thought` when on → Task 2. ✓
- agent emits orchestration `thinking` → Task 3. ✓
- surface synthesis `rationale` → Task 4. ✓
- agent emits synthesis `thinking` → Task 5. ✓
- SSE contract `{"type":"thinking","text","scope"}` → Tasks 3 & 5 emit exactly that. ✓
- no streaming client / no pipeline changes → confirmed (only persona/agent/main/primitives). ✓
- live re-verify → Task 8 step 4.1. ✓

**Spec coverage (B — upload onboarding):**
- base64 CSV content → Task 6 (`csv_b64` via `_read_csv`). ✓
- onboarding non-admin, still mutating → Task 7 (drop from ADMIN_ACTIONS, keep MUTATING). ✓
- exec/browse/self_edit/config/tools stay admin → Task 7 test asserts `exec` still gated. ✓
- live re-verify → Task 8 step 4.2. ✓

**Placeholder scan:** every code step shows complete code; every test step shows assertions + the command + expected result. No TBD/TODO. ✓

**Type/name consistency:** `reasoning_enabled()` (Task 1) used in Tasks 2/3/5; `_THOUGHT_HINT` (Task 2); the `thinking` event shape `{"type":"thinking","text","scope"}` identical in Tasks 3 & 5; `_read_csv(args, **kw)` (Task 6) used in propose/confirm; `csv_b64` arg name consistent across Tasks 6 & 7; `rationale` key flows `_run_view`/`cmd_synth` (Task 4) → agent result read (Task 5). ✓

**Note (deviation from spec, an improvement):** the spec illustrated "base64 → temp file"; this plan reads via `io.BytesIO` (no temp-file lifecycle) — strictly simpler and avoids cleanup. The onboarding is folded into the existing `onboard_propose`/`onboard_confirm` (optional `csv_b64`) rather than new action names, so the dispatch/registration is unchanged and (B) reduces to dropping `onboard_confirm` from `ADMIN_ACTIONS`.
