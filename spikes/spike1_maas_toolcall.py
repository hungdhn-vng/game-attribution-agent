"""Spike 1: does MaaS emit native OpenAI tool_calls? (OpenClaw's loop needs them.)
Throwaway probe — reads creds from env, hits {base}/chat/completions directly."""
import os, sys, json, time, httpx

BASE = os.environ["LLM_BASE_URL"].rstrip("/")
KEY = os.environ["LLM_API_KEY"]
URL = BASE + "/chat/completions"
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

TOOLS = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {"type": "object",
                       "properties": {"location": {"type": "string", "description": "City name"}},
                       "required": ["location"]}}},
    {"type": "function", "function": {
        "name": "analyze_game",
        "description": "Run an attribution analysis explaining a game's metric change.",
        "parameters": {"type": "object",
                       "properties": {"game": {"type": "string"}},
                       "required": ["game"]}}},
]
TOOL_PROMPT = "What is the current weather in Hanoi? Use the available tools to find out."
NOTOOL_PROMPT = "Reply with a one-sentence friendly greeting. Do not call any tools."


def chat(model, content, tool_choice="auto", timeout=120):
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "tools": TOOLS, "tool_choice": tool_choice, "temperature": 0}
    t = time.time()
    r = httpx.post(URL, headers=H, json=body, timeout=timeout)
    dt = round(time.time() - t, 2)
    return r, dt


def parse(r):
    if r.status_code != 200:
        return None, None, f"HTTP {r.status_code}: {r.text[:200]}"
    j = r.json()
    ch = j["choices"][0]
    msg = ch["message"]
    return msg.get("tool_calls") or [], msg.get("content"), ch.get("finish_reason")


def well_formed(tcs):
    if not tcs:
        return False, "no tool_calls"
    tc = tcs[0]
    fn = tc.get("function", {})
    name = fn.get("name")
    try:
        args = json.loads(fn.get("arguments") or "")
    except Exception:
        return False, f"{name}(UNPARSEABLE args={fn.get('arguments')!r})"
    ok = name == "get_weather" and isinstance(args, dict) and "location" in args
    return ok, f"{name}({json.dumps(args)})"


def probe(model):
    res = {"model": model}
    # --- tool-needed, auto x2 ---
    auto_oks, lats, details = 0, [], []
    for _ in range(2):
        try:
            r, dt = chat(model, TOOL_PROMPT, "auto")
            tcs, content, fin = parse(r)
            if tcs is None:
                details.append(fin); continue
            ok, d = well_formed(tcs)
            auto_oks += int(ok); lats.append(dt)
            details.append(d if tcs else f"NO_TC content={ (content or '')[:60]!r} finish={fin}")
        except Exception as e:
            details.append(f"{type(e).__name__}: {str(e)[:120]}")
    res["toolcall_auto"] = {"ok": f"{auto_oks}/2", "latency_s": lats, "samples": details}
    # --- if auto never produced a call, can it under tool_choice=required? ---
    if auto_oks == 0:
        try:
            r, dt = chat(model, TOOL_PROMPT, "required")
            tcs, content, fin = parse(r)
            if tcs is None:
                res["toolcall_required"] = {"error": fin}
            else:
                ok, d = well_formed(tcs)
                res["toolcall_required"] = {"ok": ok, "latency_s": dt, "detail": d if tcs else f"NO_TC finish={fin}"}
        except Exception as e:
            res["toolcall_required"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    # --- no-tool prompt: must NOT spuriously call ---
    try:
        r, dt = chat(model, NOTOOL_PROMPT, "auto")
        tcs, content, fin = parse(r)
        if tcs is None:
            res["no_tool"] = {"error": fin}
        else:
            res["no_tool"] = {"ok": (not tcs) and bool(content), "spurious_call": bool(tcs),
                              "latency_s": dt, "content": (content or "")[:70]}
    except Exception as e:
        res["no_tool"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return res


models = sys.argv[1:] or ["google/gemma-4-31b-it", "minimax/minimax-m2.5", "qwen/qwen3-5-27b",
                          "qwen/qwen3.7-plus", "openai/gpt-4o"]
out = []
for m in models:
    print(f"\n--- {m} ---", flush=True)
    res = probe(m)
    print(json.dumps(res, indent=2), flush=True)
    out.append(res)

print("\n================ SUMMARY ================")
for r in out:
    ta = r.get("toolcall_auto", {})
    req = r.get("toolcall_required")
    nt = r.get("no_tool", {})
    req_s = "" if req is None else f" | required={req.get('ok')}"
    nt_s = "OK" if nt.get("ok") else ("spurious!" if nt.get("spurious_call") else f"ERR({nt.get('error')})")
    print(f"{r['model']:28s} auto_toolcall={ta.get('ok')}  lat={ta.get('latency_s')}{req_s}  no_tool={nt_s}")
