from __future__ import annotations

import base64
import io
import json

import pandas as pd

from gaa.core.adapters.csv_adapter import CSVAdapter
from gaa.core.adapters.roblox_adapter import RobloxAdapter
from gaa.core.schema.profile import ColumnMapping, GameProfile


def _adapter(name: str):
    return RobloxAdapter() if name == "roblox" else CSVAdapter()


def _read_csv(args, **kw):
    """Read the onboarding CSV from base64 content (csv_b64) or a file path (csv)."""
    b64 = getattr(args, "csv_b64", None)
    if b64:
        return pd.read_csv(io.BytesIO(base64.b64decode(b64)), **kw)
    return pd.read_csv(args.csv, **kw)


def cmd_onboard_propose(ctx, args) -> dict:
    try:
        sample = _read_csv(args, nrows=20)
        mapping = ctx.profiler.propose(sample)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {
        "status": "success",
        "mapping": mapping.model_dump(),
        "message": ctx.profiler.confirmation_message(mapping),
    }


def cmd_onboard_confirm(ctx, args) -> dict:
    try:
        mapping = ColumnMapping(**json.loads(args.mapping))
        raw = _read_csv(args)
        df = _adapter(args.adapter).load(raw, mapping)
        ctx.metrics.save(args.name, df)
        ctx.profiles.save(GameProfile(
            name=args.name, platform=args.platform, genre=args.genre, mapping=mapping))
        ctx.profiles.set_active(args.name)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {
        "status": "success",
        "name": args.name,
        "row_count": int(len(df)),
        "metrics": sorted(df["metric"].unique().tolist()),
    }


def cmd_profile_list(ctx, args) -> dict:
    active = ctx.profiles.get_active()
    return {
        "status": "success",
        "profiles": ctx.profiles.list_names(),
        "active": active.name if active else None,
    }


def cmd_profile_use(ctx, args) -> dict:
    if args.name not in ctx.profiles.list_names():
        return {"status": "error", "error": f"unknown profile: {args.name!r}"}
    ctx.profiles.set_active(args.name)
    return {"status": "success", "active": args.name}
