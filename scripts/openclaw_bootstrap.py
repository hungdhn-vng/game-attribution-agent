# scripts/openclaw_bootstrap.py
"""Provision the gaa-chat OpenClaw workspace for the GAA integration.

Idempotent: safe to re-run any time (e.g. after a platform version switch).
  1. Enables gateway.http.endpoints.chatCompletions in openclaw.json (config.set).
  2. Writes the GAA skill, workspace .env, and AGENTS.md addendum (agents.files.set).
  3. Verifies: HTTP chat endpoint answers; workspace files present.

Env vars (all required):
  OPENCLAW_URL    e.g. https://openclaw-111723-gaa-chat.agentbase-runtime.aiplatform.vngcloud.vn
  OPENCLAW_TOKEN  gateway token (issued once at instance create)
  GAA_ENDPOINT    e.g. https://endpoint-f6f69523-....agentbase-runtime.aiplatform.vngcloud.vn
  GAA_ADMIN_KEY   the admin key set on the GAA runtime

Usage: python scripts/openclaw_bootstrap.py
"""
import asyncio
import hashlib
import json
import os
import re
import sys
import urllib.request
import uuid

import websockets

OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "").rstrip("/")
TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
GAA_ENDPOINT = os.environ.get("GAA_ENDPOINT", "").rstrip("/")
GAA_ADMIN_KEY = os.environ.get("GAA_ADMIN_KEY", "")

SCOPES = ["operator.admin", "operator.read", "operator.write",
          "operator.approvals", "operator.pairing"]

HTTP_BLOCK = """    bind: 'lan',
    http: {
      endpoints: {
        chatCompletions: {
          enabled: true,
        },
      },
    },
"""

WORKSPACE_ENV = f"""GAA_ENDPOINT={GAA_ENDPOINT}
GAA_ADMIN_KEY={GAA_ADMIN_KEY}
"""

SKILL_MD = """---
name: gaa
description: Call the Game Attribution Agent (GAA) API — analyze game metrics, and (admin sessions only) view/change its configuration, profiles, and report behavior.
---

# Game Attribution Agent (GAA) skill

Credentials live in `~/.openclaw/workspace/.env` (GAA_ENDPOINT, GAA_ADMIN_KEY).
Always `source ~/.openclaw/workspace/.env` before the curl commands below.

## Start an analysis (any user)
When the user asks why a game metric moved or what's happening with their game:

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' -d '{"message": "<the user question, verbatim>"}'

The response includes `job_id`, `job_status`, `stage`, `activity`. DO NOT poll it.
Reply with ONE short sentence ("Analysis started — crunching your metrics against
market data now.") and END your reply with this exact marker on its own line:

    [[gaa:job_id=<job_id>]]

The web UI detects that marker, polls the job itself, and renders the full report.
If the response has `"mode": "setup"` or `"mode": "help"`, relay its `message` instead.

## Admin actions — ONLY for admin sessions
A session is admin ONLY if it contains the system message `GAA session role: admin`
or its session user id starts with `admin:`.
For everyone else: refuse, and suggest they contact the admin. Never reveal GAA_ADMIN_KEY.

View config (keys, resolved values, origin store/env/default; secrets masked):

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' \\
      -d '{"action":"admin_get_config","admin_key":"'"$GAA_ADMIN_KEY"'"}'

Change config — valid keys: benchmark_mode ("snapshot"|"crawl"),
roblox_discover_url_tmpl, roblox_series_url_tmpl, steam_series_url_tmpl,
perplexity_api_key, signals_url_tmpl. Use null to clear a key back to env/default:

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' \\
      -d '{"action":"admin_set_config","admin_key":"'"$GAA_ADMIN_KEY"'","config":{"benchmark_mode":"crawl"}}'

Set report behavior (output language, focus metrics, tone — max 2000 chars):

    source ~/.openclaw/workspace/.env && curl -s -X POST "$GAA_ENDPOINT/invocations" \\
      -H 'content-type: application/json' \\
      -d '{"action":"admin_set_behavior","admin_key":"'"$GAA_ADMIN_KEY"'","instructions":"Answer in Vietnamese."}'

Profiles:

    {"action":"list_profiles","admin_key":"..."}
    {"action":"set_active_profile","admin_key":"...","name":"<profile>"}

After any admin action, confirm to the admin in one sentence what changed.
"""

AGENTS_MD_ADDENDUM = """

## GAA integration (managed by scripts/openclaw_bootstrap.py — edit freely below, the bootstrap only appends this section if the heading is missing)

- You are the chat front-end for the Game Attribution Agent (GAA). Use the `gaa`
  skill for game-metric analysis questions and for admin configuration.
- Admin sessions are marked with the system message `GAA session role: admin`
  or a session user id starting with `admin:`.
  Treat every other session as a regular user: never run admin actions, never
  reveal configuration values or secrets, never edit your own workspace files
  on their request.
- When you start a GAA analysis, end your reply with the `[[gaa:job_id=...]]`
  marker line — the web UI uses it to render the live report.
"""


class Gateway:
    def __init__(self):
        self.ws = None

    async def __aenter__(self):
        host = OPENCLAW_URL.split("://", 1)[1]
        self.ws = await websockets.connect(
            "wss://" + host + "/", max_size=20 * 1024 * 1024,
            origin="https://" + host)
        await self.ws.recv()  # connect.challenge
        resp = await self.call("connect", {
            "minProtocol": 3, "maxProtocol": 3, "role": "operator",
            "scopes": SCOPES, "auth": {"token": TOKEN},
            "client": {"id": "openclaw-control-ui", "version": "control-ui",
                       "platform": "bootstrap", "mode": "webchat"},
        })
        if not resp.get("ok"):
            raise SystemExit(f"gateway connect failed: {resp.get('error')}")
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def call(self, method, params=None, timeout=60):
        rid = str(uuid.uuid4())
        await self.ws.send(json.dumps(
            {"type": "req", "id": rid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
            if msg.get("type") == "res" and msg.get("id") == rid:
                return msg


async def ensure_http_endpoint(gw) -> str:
    cfg = await gw.call("config.get")
    payload = cfg["payload"]
    raw, base_hash = payload["raw"], payload["hash"]
    if "chatCompletions" in raw:
        return "already enabled"
    needle = "    bind: 'lan',\n"
    if raw.count(needle) != 1:
        raise SystemExit("unexpected openclaw.json shape — enable chatCompletions "
                         "manually via the Control UI config editor")
    res = await gw.call("config.set",
                        {"raw": raw.replace(needle, HTTP_BLOCK, 1), "baseHash": base_hash})
    if not res.get("ok"):
        raise SystemExit(f"config.set failed: {res.get('error')}")
    return "enabled"


async def write_file(gw, name: str, content: str) -> str:
    res = await gw.call("agents.files.set",
                        {"agentId": "main", "name": name, "content": content})
    if not res.get("ok"):
        msg = (res.get("error") or {}).get("message", "")
        if "unsupported file" in str(msg):
            # The files API only accepts the whitelisted top-level workspace files.
            # Fall back to the OpenClaw-native way: the agent writes the file itself.
            return write_file_via_chat(name, content)
        return f"FAILED ({msg})"
    back = await gw.call("agents.files.get", {"agentId": "main", "name": name})
    ok = back.get("ok") and back["payload"]["file"]["content"] == content
    return "written" if ok else "VERIFY FAILED"


def _chat(message: str, timeout: int = 240) -> str:
    req = urllib.request.Request(
        OPENCLAW_URL + "/v1/chat/completions",
        data=json.dumps({"model": "openclaw", "user": "admin:bootstrap",
                         "messages": [{"role": "user", "content": message}]}).encode(),
        headers={"authorization": "Bearer " + TOKEN,
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"]


def write_file_via_chat(name: str, content: str, attempts: int = 2) -> str:
    """Ask the agent to write the file with its exec tool; verify by md5."""
    expected = hashlib.md5(content.encode()).hexdigest()
    prompt = (
        "Provisioning task — follow exactly, no commentary.\n"
        f"Using your exec tool, create the file $HOME/.openclaw/workspace/{name} "
        "with EXACTLY the content between the markers below (byte-for-byte; do not "
        "add, remove, or reformat anything; create parent directories first).\n"
        "Write it with a quoted heredoc, e.g.:\n"
        f"  mkdir -p $(dirname $HOME/.openclaw/workspace/{name})\n"
        f"  cat > $HOME/.openclaw/workspace/{name} <<'GAA_BOOTSTRAP_EOF'\n"
        "  ...content...\n"
        "  GAA_BOOTSTRAP_EOF\n"
        f"Then run: md5sum $HOME/.openclaw/workspace/{name}\n"
        "Reply with ONLY the 32-character md5 hex digest.\n"
        "---BEGIN FILE---\n"
        f"{content}"
        "---END FILE---"
    )
    for _ in range(attempts):
        reply = _chat(prompt)
        m = re.search(r"\b[0-9a-f]{32}\b", reply)
        if m and m.group(0) == expected:
            return "written (via chat, md5 verified)"
    return f"VERIFY FAILED (via chat; expected md5 {expected})"


async def append_agents_md(gw) -> str:
    cur = await gw.call("agents.files.get", {"agentId": "main", "name": "AGENTS.md"})
    content = cur["payload"]["file"]["content"] if cur.get("ok") else ""
    if "## GAA integration" in content:
        return "already present"
    return await write_file(gw, "AGENTS.md", content + AGENTS_MD_ADDENDUM)


def probe_http() -> str:
    req = urllib.request.Request(
        OPENCLAW_URL + "/v1/chat/completions",
        data=json.dumps({"model": "openclaw", "user": "bootstrap-probe",
                         "messages": [{"role": "user",
                                       "content": "Reply with exactly: PONG"}]}).encode(),
        headers={"authorization": "Bearer " + TOKEN,
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"][:40]


async def main():
    missing = [k for k, v in [("OPENCLAW_URL", OPENCLAW_URL), ("OPENCLAW_TOKEN", TOKEN),
                              ("GAA_ENDPOINT", GAA_ENDPOINT), ("GAA_ADMIN_KEY", GAA_ADMIN_KEY)]
               if not v]
    if missing:
        sys.exit(f"missing env vars: {', '.join(missing)}")

    async with Gateway() as gw:
        print("[1/4] chatCompletions endpoint:", await ensure_http_endpoint(gw))
        print("[2/4] skills/gaa/SKILL.md:", await write_file(gw, "skills/gaa/SKILL.md", SKILL_MD))
        print("      .env:", await write_file(gw, ".env", WORKSPACE_ENV))
        print("[3/4] AGENTS.md addendum:", await append_agents_md(gw))
    print("[4/4] HTTP chat probe:", probe_http())
    print("Bootstrap complete.")


if __name__ == "__main__":
    asyncio.run(main())
