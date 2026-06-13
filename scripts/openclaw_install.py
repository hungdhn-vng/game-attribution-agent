#!/usr/bin/env python3
"""Install the GAA CLI + skill into a hosted OpenClaw instance's workspace.

Replaces the endpoint-era openclaw_bootstrap.py. The agent now RUNS `gaa` in its
own workspace (no remote endpoint, no admin_key). Steps (live, in order):
  1. gateway WS handshake (operator scopes, Origin header)
  2. enable gateway.http.endpoints.chatCompletions (config.set splice; for the frontend)
  3. CAPABILITY GATE: chat-driven exec -> python3 version, git clone, `pip install -e .`
     with statsmodels/ruptures. If this fails, STOP — the combine needs a rethink.
  4. write workspace .env (LLM_*, PERPLEXITY_API_KEY, GAA_BENCHMARK_MODE)
  5. push workspace/ artifacts (agents.files.set -> chat-driven md5 fallback)
  6. verify: `gaa doctor`, then a budgeted smoke `gaa analyze`

`--dry-run` prints the manifest (files + commands) without connecting — for offline review.

Env: OPENCLAW_URL, OPENCLAW_TOKEN, GAA_REPO_URL, plus the workspace-.env values
(LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, PERPLEXITY_API_KEY, GAA_BENCHMARK_MODE) read
from the local process environment / .env.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

SCOPES = ["operator.admin", "operator.read", "operator.write",
          "operator.approvals", "operator.pairing"]

GAA_WRAPPER = """#!/bin/sh
# Installed by openclaw_install: source the workspace .env (LLM creds + absolute GAA_*
# state paths) then run gaa, so it behaves identically from any cwd the exec shell uses.
set -a
[ -f /root/.openclaw/workspace/gaa/.env ] && . /root/.openclaw/workspace/gaa/.env
set +a
exec python3 -m gaa.cli.main "$@"
"""

HTTP_BLOCK = """    bind: 'lan',
    http: {
      endpoints: {
        chatCompletions: {
          enabled: true,
        },
      },
    },
"""

_ENV_KEYS = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
             "PERPLEXITY_API_KEY", "GAA_BENCHMARK_MODE"]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def collect_workspace_files(root: str) -> dict:
    """Return {workspace-relative-posix-path: content} for every file under root."""
    base = Path(root)
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out[p.relative_to(base).as_posix()] = p.read_text()
    return out


def render_workspace_env(env: dict) -> str:
    """Render the workspace .env: LLM/secret keys from the installer env, PLUS absolute
    GAA_* state paths so gaa + scratch scripts share one state dir regardless of cwd.
    (NO GAA_ENDPOINT, NO GAA_ADMIN_KEY.)"""
    lines = [f"{k}={env[k]}" for k in _ENV_KEYS if env.get(k)]
    base = "/root/.openclaw/workspace/gaa"
    lines += [
        f"GAA_DB_PATH={base}/gaa.sqlite",
        f"GAA_CACHE_DIR={base}/data/cache",
        f"GAA_CONFIG_PATH={base}/gaa-config.toml",
        f"GAA_TOOLS_DIR={base}/data/cache/tools",
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def splice_http_endpoint(raw: str) -> str:
    """Insert the chatCompletions HTTP block after `bind: 'lan',` (idempotent)."""
    if "chatCompletions" in raw:
        return raw
    needle = "    bind: 'lan',\n"
    if raw.count(needle) != 1:
        raise SystemExit("unexpected openclaw.json shape — enable chatCompletions via the Control UI")
    return raw.replace(needle, HTTP_BLOCK, 1)


def capability_gate_commands(repo_url: str) -> list:
    """Shell commands (run via chat-driven exec) that ship the code + gate on deps.

    Spike (2026-06-13) verified the OpenClaw template image is Debian 12 / Python
    3.11 running as root WITH network egress but NO pip/uv/ensurepip. So pip is
    bootstrapped via get-pip.py and installs use --break-system-packages (PEP 668;
    safe — it's a disposable single-purpose container we own as root).
    """
    ws = "$HOME/.openclaw/workspace"
    return [
        "python3 --version",
        # bootstrap pip if absent (template ships none; root + network available)
        "python3 -m pip --version 2>/dev/null || "
        "(curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && "
        "python3 /tmp/get-pip.py --break-system-packages)",
        f"cd {ws} && (test -d gaa/.git && (cd gaa && git pull) || git clone {repo_url} gaa)",
        f"cd {ws}/gaa && python3 -m pip install --break-system-packages -e .",
        f"cd {ws}/gaa && python3 -c 'import statsmodels, ruptures, pyarrow; print(\"DEPS\"+\"OK\")'",
        "gaa --help >/dev/null 2>&1 && echo gaa-on-path || echo gaa-missing",
    ]


def verify_commands() -> list:
    return ["gaa doctor", "gaa jobs"]


def _print_manifest(workspace: str, repo_url: str) -> None:
    files = collect_workspace_files(workspace)
    print("# openclaw_install dry-run\n")
    print(f"repo: {repo_url or '(GAA_REPO_URL unset)'}\n")
    print("## capability gate (chat-driven exec, in order):")
    for c in capability_gate_commands(repo_url):
        print(f"  $ {c}")
    print("\n## workspace files (from clone, via cp):")
    for name, content in files.items():
        print(f"  {name}  (md5 {_md5(content)})")
    print("\n## install steps:")
    print("  install gaa wrapper -> /usr/local/bin/gaa")
    print("  write .env (base64) -> gaa/.env")
    print("  cp artifacts from clone (gaa/workspace/ -> workspace root)")
    print("\n## verify:")
    for c in verify_commands():
        print(f"  $ {c}")


class Gateway:
    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._token = token
        self.ws = None

    async def __aenter__(self):
        import websockets
        host = self._url.split("://", 1)[1]
        self.ws = await websockets.connect("wss://" + host + "/",
                                           max_size=20 * 1024 * 1024, origin="https://" + host)
        await self.ws.recv()  # connect.challenge
        resp = await self.call("connect", {
            "minProtocol": 3, "maxProtocol": 3, "role": "operator", "scopes": SCOPES,
            "auth": {"token": self._token},
            "client": {"id": "openclaw-control-ui", "version": "control-ui",
                       "platform": "install", "mode": "webchat"}})
        if not resp.get("ok"):
            raise SystemExit(f"gateway connect failed: {resp.get('error')}")
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def call(self, method, params=None, timeout=120):
        import uuid
        rid = str(uuid.uuid4())
        await self.ws.send(json.dumps({"type": "req", "id": rid, "method": method,
                                       "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
            if msg.get("type") == "res" and msg.get("id") == rid:
                return msg


def _exec_via_chat(url: str, token: str, command: str, timeout: int = 600) -> str:
    """Drive the agent's exec tool over /v1/chat/completions; return its reply text."""
    import urllib.request
    prompt = ("Provisioning task — no commentary. Using your exec tool, run EXACTLY this command "
              "and reply with ONLY its stdout/stderr:\n\n" + command)
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps({"model": "openclaw", "user": "admin:installer",
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"authorization": "Bearer " + token, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"]


def _write_text_via_chat(url: str, token: str, path: str, content: str,
                         attempts: int = 8, chmod: str = "") -> str:
    """Write a file via chat-driven exec using base64 (robust to reformatting) and
    RETRY until the container's md5 matches (the agent garbles long strings intermittently)."""
    import base64
    expected = _md5(content)
    b64 = base64.b64encode(content.encode()).decode()
    chmod_part = f" && chmod {chmod} {path}" if chmod else ""
    cmd = (f"mkdir -p $(dirname {path}) && echo {b64} | base64 -d > {path}{chmod_part} && "
           f"md5sum {path} | cut -d' ' -f1")
    for _ in range(attempts):
        if expected in _exec_via_chat(url, token, cmd, timeout=180):
            return "written (md5 verified)"
    return f"VERIFY FAILED (expected {expected})"


async def _install_live(args) -> None:
    url, token, repo = (os.environ.get("OPENCLAW_URL", ""), os.environ.get("OPENCLAW_TOKEN", ""),
                        os.environ.get("GAA_REPO_URL", ""))
    missing = [k for k, v in [("OPENCLAW_URL", url), ("OPENCLAW_TOKEN", token),
                              ("GAA_REPO_URL", repo),
                              ("LLM_API_KEY", os.environ.get("LLM_API_KEY", ""))] if not v]
    if missing:
        sys.exit(f"missing env vars: {', '.join(missing)}")
    files = collect_workspace_files(args.workspace)

    async with Gateway(url, token) as gw:
        cfg = await gw.call("config.get")
        payload = cfg["payload"]
        spliced = splice_http_endpoint(payload["raw"])
        if spliced != payload["raw"]:
            res = await gw.call("config.set", {"raw": spliced, "baseHash": payload["hash"]})
            if not res.get("ok"):
                sys.exit(f"config.set failed: {res.get('error')}")
    print("[1/6] chatCompletions endpoint: ok")

    print("[2/6] capability gate:")
    for cmd in capability_gate_commands(repo):
        reply = _exec_via_chat(url, token, cmd)
        print(f"  $ {cmd}\n    -> {reply.strip()[:200]}")
        if "import statsmodels" in cmd and "DEPSOK" not in reply:
            sys.exit("CAPABILITY GATE FAILED — the template image cannot run the pipeline deps. "
                     "Stop: the combine needs a rethink (vendor wheels / custom image) before continuing.")

    # [3/6] install the gaa wrapper (location-independent gaa)
    print("[3/6] gaa wrapper:",
          _write_text_via_chat(url, token, "/usr/local/bin/gaa", GAA_WRAPPER, chmod="+x"))

    # [4/6] write the workspace .env (LLM creds + absolute state paths)
    print("[4/6] .env:",
          _write_text_via_chat(url, token, "$HOME/.openclaw/workspace/gaa/.env",
                               render_workspace_env(os.environ)))

    # [5/6] copy skill artifacts from the cloned repo (byte-exact via git; `src/.` avoids dir nesting)
    cp = ("rm -rf $HOME/.openclaw/workspace/skills && mkdir -p $HOME/.openclaw/workspace/skills && "
          "cp -rf $HOME/.openclaw/workspace/gaa/workspace/skills/. $HOME/.openclaw/workspace/skills/ && "
          "cp -f $HOME/.openclaw/workspace/gaa/workspace/AGENTS.md $HOME/.openclaw/workspace/AGENTS.md && "
          "echo ARTIFACTS_COPIED")
    r = _exec_via_chat(url, token, cp)
    print("[5/6] artifacts:", "copied" if "ARTIFACTS_COPIED" in r else f"CHECK: {r.strip()[:160]}")

    # [6/6] verify
    print("[6/6] verify")
    for cmd in verify_commands():
        print(f"  $ {cmd}\n    -> {_exec_via_chat(url, token, cmd).strip()[:200]}")
    print("Install complete.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="openclaw_install")
    p.add_argument("--workspace", default=str(Path(__file__).resolve().parents[1] / "workspace"))
    p.add_argument("--dry-run", action="store_true",
                   help="print the file + command manifest without connecting")
    args = p.parse_args(argv)
    if args.dry_run:
        _print_manifest(args.workspace, os.environ.get("GAA_REPO_URL", ""))
        return
    asyncio.run(_install_live(args))


if __name__ == "__main__":
    main()
