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
    """Read the onboarding CSV from base64 content (csv_b64) or a file path (csv).

    NA-safe: keep_default_na=False so dimension values like "NA" (North America),
    "N/A", or "null" survive instead of being parsed as NaN and silently dropped
    from every dimensional analysis; only a truly empty cell counts as missing.
    """
    read_kw = {"keep_default_na": False, "na_values": [""], **kw}
    b64 = getattr(args, "csv_b64", None)
    if b64:
        return pd.read_csv(io.BytesIO(base64.b64decode(b64)), **read_kw)
    return pd.read_csv(args.csv, **read_kw)


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
        profile = GameProfile(
            name=args.name, platform=args.platform, genre=args.genre, mapping=mapping)
        from gaa.core.crawl.roblox_title import universe_id_from, lookup_universe_title
        if getattr(profile, "title", None) is None and profile.platform == "roblox":
            uid = universe_id_from(profile.name)
            if uid:
                profile.title = lookup_universe_title(uid)  # None on failure → genre-scoped fallback
        ctx.profiles.save(profile)
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
