from __future__ import annotations

import json

import pandas as pd

from gaa.core.adapters.csv_adapter import CSVAdapter
from gaa.core.adapters.roblox_adapter import RobloxAdapter
from gaa.core.schema.profile import ColumnMapping, GameProfile


def _adapter(name: str):
    return RobloxAdapter() if name == "roblox" else CSVAdapter()


def cmd_onboard_propose(ctx, args) -> dict:
    try:
        sample = pd.read_csv(args.csv, nrows=20)
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
        raw = pd.read_csv(args.csv)
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
