"""Thin stdio MCP adapter: exposes gaa.mcp.tools over the MCP protocol for OpenClaw.
is_admin source set by GAA_MCP_ADMIN env var (container/shim sets it)."""
from __future__ import annotations

import asyncio
import json
import os

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from gaa.cli.wiring import build_context
from gaa.mcp import tools


def _is_admin() -> bool:
    return os.environ.get("GAA_MCP_ADMIN", "").strip().lower() in ("1", "true", "yes", "on")


def build_server(ctx, *, is_admin: bool) -> Server:
    srv = Server("gaa")

    @srv.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in tools.tool_specs(is_admin=is_admin)
        ]

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = tools.run_tool(ctx, name, arguments or {}, is_admin=is_admin)
        return [types.TextContent(type="text", text=json.dumps(result))]

    return srv


def _for_test_handles(*, is_admin: bool):
    """Expose registered list/call handlers synchronously for unit tests.

    SDK adaptation notes (mcp 1.27.x):
    - Handlers live in srv.request_handlers keyed by types.ListToolsRequest / types.CallToolRequest
    - list handler returns ServerResult wrapping ListToolsResult; extract via .root.tools
    - call handler returns ServerResult wrapping CallToolResult; extract via .root.content
    - Tool cache auto-populates on first call_tool miss (calls list handler internally).
    """
    ctx = build_context()
    srv = build_server(ctx, is_admin=is_admin)

    def listed() -> list[types.Tool]:
        req = types.ListToolsRequest(method="tools/list")
        result = asyncio.run(
            srv.request_handlers[types.ListToolsRequest](req)
        )
        return result.root.tools

    def called(name: str, args: dict) -> list[types.TextContent]:
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=args),
        )
        result = asyncio.run(
            srv.request_handlers[types.CallToolRequest](req)
        )
        return result.root.content

    return srv, listed, called


def main() -> None:
    ctx = build_context()
    srv = build_server(ctx, is_admin=_is_admin())

    async def _run():
        async with stdio_server() as (read, write):
            await srv.run(read, write, srv.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
