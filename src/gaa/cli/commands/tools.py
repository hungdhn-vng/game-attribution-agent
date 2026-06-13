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


def cmd_tools_list(ctx, args) -> dict:
    return {"status": "success", "tools": ctx.tools.list()}


def cmd_tools_show(ctx, args) -> dict:
    try:
        return {"status": "success", **ctx.tools.show(args.name)}
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}


def cmd_tools_remove(ctx, args) -> dict:
    try:
        ctx.tools.remove(args.name)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "removed": args.name}


def cmd_tools_sync_docs(ctx, args) -> dict:
    out = args.out or os.environ.get("GAA_TOOLS_DOC_PATH") or str(ctx.tools._root / "tools.md")
    ctx.tools.sync_docs(out)
    return {"status": "success", "doc_path": out}


def cmd_tools_export(ctx, args) -> dict:
    ctx.tools.export(args.out)
    return {"status": "success", "tarball": args.out}


def cmd_tools_import(ctx, args) -> dict:
    try:
        ctx.tools.import_(args.tarball)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "tools": ctx.tools.list()}


def cmd_tools_run(ctx, args) -> dict:
    import subprocess
    import sys

    try:
        ok = ctx.tools.verify(args.name)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    if not ok:
        return {"status": "error",
                "error": f"tool {args.name!r} failed md5 verification (changed since promotion) — re-promote it"}

    env = {**os.environ, "GAA_TOOL_NAME": args.name}
    if args.run:
        env["GAA_RUN_ID"] = args.run
    if args.args:
        env["GAA_TOOL_ARGS"] = args.args
    try:
        proc = subprocess.run(
            [sys.executable, str(ctx.tools.path(args.name))],
            env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"tool {args.name!r} timed out (120s)"}
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "tool": args.name,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
        **({"error": f"tool exited {proc.returncode}"} if proc.returncode != 0 else {}),
    }
