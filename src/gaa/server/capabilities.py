"""General agent capabilities cloned from OpenClaw: exec (arbitrary shell), browse
(fetch + read a web page), self_edit (rewrite SOUL.md/MEMORY.md). All are admin-gated
(see gaa.server.actions). browse uses httpx + BeautifulSoup (already deps) — no headless
browser, so no JS-rendered pages, but a small image. Each handler is `(ctx, args) -> dict`
to match the CLI handler shape, and is registered into the shared dispatch at import time.
"""
from __future__ import annotations

import subprocess

import httpx
from bs4 import BeautifulSoup

from gaa.server import actions, persona

_EXEC_TIMEOUT_S = 120
_BROWSE_TIMEOUT_S = 30
_BROWSE_MAX_CHARS = 8000


def exec_action(ctx, args) -> dict:
    command = getattr(args, "command", None)
    if not command:
        return {"status": "error", "error": "exec requires a 'command' string"}
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              timeout=_EXEC_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"command timed out ({_EXEC_TIMEOUT_S}s)"}
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:].decode("utf-8", "replace"),
        "stderr": proc.stderr[-2000:].decode("utf-8", "replace"),
        **({"error": f"exit {proc.returncode}"} if proc.returncode != 0 else {}),
    }


def browse_action(ctx, args) -> dict:
    url = getattr(args, "url", None)
    if not url:
        return {"status": "error", "error": "browse requires a 'url'"}
    try:
        resp = httpx.get(url, timeout=_BROWSE_TIMEOUT_S, follow_redirects=True,
                         headers={"User-Agent": "gaa-agent/1.0"})
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "error", "error": f"fetch failed: {exc}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = " ".join(soup.get_text(separator=" ").split())
    return {"status": "success", "url": url, "title": title, "text": text[:_BROWSE_MAX_CHARS]}


def self_edit_action(ctx, args) -> dict:
    persona.ensure_seeded(ctx)
    target = getattr(args, "target", None)
    content = getattr(args, "content", None)
    mode = getattr(args, "mode", None) or "replace"
    if content is None:
        return {"status": "error", "error": "self_edit requires 'content'"}
    try:
        n = persona.write_persona(ctx, target, content, mode=mode)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "target": target, "bytes": n, "mode": mode}


# Register into the shared dispatch (admin-gated; self_edit also triggers a snapshot).
actions.register("exec", exec_action, admin=True)
actions.register("browse", browse_action, admin=True)
actions.register("self_edit", self_edit_action, admin=True, mutating=True)
