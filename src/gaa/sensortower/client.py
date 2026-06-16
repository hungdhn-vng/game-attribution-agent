"""Sensor Tower MCP client. A shared background asyncio loop lets the sync MCP-tool
dispatch (gaa.mcp.tools.run_tool) block on async ST calls. One short-lived ST session
per call keeps lifecycle trivial; the access token is managed by gaa.sensortower.oauth.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from gaa.sensortower import config

_loop = None
_lock = threading.Lock()
_CALL_TIMEOUT_S = 60  # max wait for a single ST MCP round-trip before the sync caller unblocks


def _bg_loop():
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop


def _run(coro, timeout=_CALL_TIMEOUT_S):
    # On timeout the coroutine keeps running on _bg_loop until the HTTP layer closes it;
    # acceptable for single-user demo traffic.
    return asyncio.run_coroutine_threadsafe(coro, _bg_loop()).result(timeout)


@asynccontextmanager
async def _open_session(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(config.base_url(), headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def list_tools(access_token: str) -> list[dict]:
    async def _go():
        async with _open_session(access_token) as session:
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema,
                }
                for t in result.tools
            ]

    return _run(_go())


def call_tool(access_token: str, name: str, arguments: dict) -> dict:
    async def _go():
        async with _open_session(access_token) as session:
            result = await session.call_tool(name, arguments or {})
            # ST responses are text/JSON; image/embedded-resource blocks are intentionally dropped.
            texts = [
                c.text
                for c in result.content
                if getattr(c, "type", None) == "text"
            ]
            return {"content": texts, "is_error": bool(getattr(result, "isError", False))}

    return _run(_go())
