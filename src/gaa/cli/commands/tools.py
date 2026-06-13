from __future__ import annotations

import os


def cmd_tools_promote(ctx, args) -> dict:
    script = args.script
    if args.run and not os.path.isabs(script) and not os.path.exists(script):
        script = str(ctx.runs.path_for(args.run) / "scratch" / args.script)
    try:
        meta = ctx.tools.promote(
            args.name, args.description, script,
            source_run=args.run or "", source_script=args.script)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "tool": meta["name"], "md5": meta["md5"],
            "provenance": meta["provenance"]}
