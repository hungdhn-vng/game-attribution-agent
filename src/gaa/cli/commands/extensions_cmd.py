"""Admin management actions: register/unregister MCP servers and manage secrets.
Handlers take (ctx, args) where args is an argparse-Namespace-like object whose
unset attributes are None (see gaa.server.actions._Args)."""
from __future__ import annotations

from gaa.server import extensions


def cmd_mcp_add(ctx, args) -> dict:
    try:
        entry = extensions.add_server(
            name=args.name, command=args.command, args=args.args or [],
            url=args.url, env=args.env or {})
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    extensions.request_reload()
    return {"status": "success", "server": entry,
            "note": "Reloading the runtime so the new tools become available."}


def cmd_mcp_remove(ctx, args) -> dict:
    removed = extensions.remove_server(args.name)
    extensions.request_reload()
    return {"status": "success", "removed": removed}


def cmd_mcp_list(ctx, args) -> dict:
    return {"status": "success", "servers": extensions.list_servers()}


def cmd_secret_set(ctx, args) -> dict:
    if not args.value:
        return {"status": "error", "error": "value is required"}
    try:
        extensions.set_secret(args.name, args.value)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    extensions.request_reload()
    return {"status": "success", "name": args.name}


def cmd_secret_unset(ctx, args) -> dict:
    removed = extensions.unset_secret(args.name)
    extensions.request_reload()
    return {"status": "success", "removed": removed}


def cmd_secret_list(ctx, args) -> dict:
    return {"status": "success", "names": extensions.list_secret_names()}
