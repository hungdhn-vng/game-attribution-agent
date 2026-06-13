from __future__ import annotations

from gaa.config import KEYS


def cmd_config_get(ctx, args) -> dict:
    if args.key:
        try:
            value, origin = ctx.config.resolve(args.key)
        except KeyError as exc:
            return {"status": "error", "error": str(exc)}
        if KEYS[args.key].secret and value:
            value = "…" + value[-4:]
        return {"status": "success", "key": args.key, "value": value, "origin": origin}
    return {"status": "success", "config": ctx.config.all_resolved()}


def cmd_config_set(ctx, args) -> dict:
    try:
        ctx.config.set(args.key, args.value)
    except (KeyError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "config": ctx.config.all_resolved()}
