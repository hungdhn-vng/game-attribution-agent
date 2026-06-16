"""Tests for gaa.sensortower.client.

The in-memory server/session pair from mcp.shared.memory exercises the real
list_tools/call_tool mapping (schema→input_schema, content→list[str]) without
hitting the network.

Background-loop note: the production _run dispatches via asyncio.run_coroutine_threadsafe
onto a shared daemon thread loop — and that works fine in testing too (verified in a
standalone probe). We keep the production _run as-is and do NOT monkeypatch it.
"""
from contextlib import asynccontextmanager

import mcp.types as types
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_session as _connect

from gaa.sensortower import client as st_client


def _fake_st_server() -> Server:
    srv = Server("fake-st")

    @srv.list_tools()
    async def _lt():
        return [
            types.Tool(
                name="get_app",
                description="Get app stats",
                inputSchema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            )
        ]

    @srv.call_tool()
    async def _ct(name, arguments):
        return [types.TextContent(type="text", text=f"{name}:{arguments.get('id')}")]

    return srv


def _patch_open_session(monkeypatch):
    # _open_session must be an async CM yielding a started ClientSession; _connect already is.
    @asynccontextmanager
    async def fake_open_session(_token):
        async with _connect(_fake_st_server()) as session:
            yield session

    monkeypatch.setattr(st_client, "_open_session", fake_open_session)


def test_list_tools_maps_schema(monkeypatch):
    _patch_open_session(monkeypatch)
    tools = st_client.list_tools("AT")
    assert tools == [
        {
            "name": "get_app",
            "description": "Get app stats",
            "input_schema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
        }
    ]


def test_call_tool_returns_text_content(monkeypatch):
    _patch_open_session(monkeypatch)
    out = st_client.call_tool("AT", "get_app", {"id": "42"})
    assert out["content"] == ["get_app:42"]
    assert out["is_error"] is False
