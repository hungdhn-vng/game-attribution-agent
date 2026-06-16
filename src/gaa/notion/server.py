"""stdio MCP adapter for the Notion read tools. Mirrors gaa.mcp.server.

Entry point: python -m gaa.notion.server
"""
from __future__ import annotations

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from gaa.notion import tools


def build_server() -> Server:
    srv = Server("notion")

    @srv.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
            for t in tools.tool_specs()
        ]

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = tools.run_tool(name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result))]

    return srv


def _for_test_handles():
    """Expose registered list/call handlers synchronously for unit tests
    (mcp 1.27.x: handlers in srv.request_handlers; results unwrap via .root)."""
    srv = build_server()

    def listed() -> list[types.Tool]:
        req = types.ListToolsRequest(method="tools/list")
        return asyncio.run(srv.request_handlers[types.ListToolsRequest](req)).root.tools

    def called(name: str, args: dict) -> list[types.TextContent]:
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=args),
        )
        return asyncio.run(srv.request_handlers[types.CallToolRequest](req)).root.content

    return srv, listed, called


def main() -> None:
    srv = build_server()

    async def _run():
        async with stdio_server() as (read, write):
            await srv.run(read, write, srv.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
