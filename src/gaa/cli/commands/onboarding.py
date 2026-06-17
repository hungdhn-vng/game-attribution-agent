from __future__ import annotations

import base64
import json
from typing import Optional

from gaa.core.ingest import detect
from gaa.core.ingest.detect import IngestError
from gaa.core.ingest.readers.base import RawTable
from gaa.core.adapters.plan_adapter import PlanAdapter
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
from gaa.core.schema.profile import GameProfile

AUTO_CONFIDENCE = 0.8


def _content_b64(args) -> Optional[str]:
    # content_b64 is the canonical field; csv_b64 is the legacy alias.
    return getattr(args, "content_b64", None) or getattr(args, "csv_b64", None)


def _read(args, spec: Optional[ReadSpec] = None) -> RawTable:
    """Read from pasted text, base64 content (any format), or a file path."""
    text = getattr(args, "text", None)
    if text:
        return detect.read_any(text=text, spec=spec)
    b64 = _content_b64(args)
    fname = getattr(args, "filename", None)
    if b64:
        return detect.read_any(content=base64.b64decode(b64), filename=fname, spec=spec)
    path = getattr(args, "csv", None)
    if path:
        with open(path, "rb") as f:
            return detect.read_any(content=f.read(), filename=fname or path, spec=spec)
    raise IngestError("unreadable_file", "no input provided",
                      "attach a file or paste a table")


def _plan_arg(args) -> IngestionPlan:
    raw = args.plan
    data = json.loads(raw) if isinstance(raw, str) else raw
    return IngestionPlan(**data)


def cmd_onboard_propose(ctx, args) -> dict:
    try:
        raw = _read(args)
    except IngestError as e:
        return e.as_dict()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "unreadable_file", "detail": str(exc),
                "hint": "supported: CSV/TSV, Excel, JSON/JSONL, or a pasted table"}

    plan = None
    for _ in range(2):  # retry once on an invalid plan from the model
        try:
            plan = ctx.profiler.propose(raw)
            break
        except Exception:
            plan = None
    if plan is None:
        return {"status": "error", "error": "cannot_interpret",
                "detail": f"columns: {list(raw.df.columns)}",
                "hint": "tell me which column is the date and which are the metrics"}

    try:
        preview_df = PlanAdapter().load(raw.df, plan).head(8)
    except IngestError:
        preview_df = raw.df.head(5)

    return {
        "status": "success",
        "plan": plan.model_dump(),
        "summary": ctx.profiler.summary(plan, preview_df),
        "preview": preview_df.astype(str).to_dict(orient="records"),
        "confidence": plan.confidence,
        "auto_ok": plan.confidence >= AUTO_CONFIDENCE and not plan.notes,
    }


def cmd_onboard_confirm(ctx, args) -> dict:
    try:
        plan = _plan_arg(args)
        raw = _read(args, spec=plan.read_spec)
        df = PlanAdapter().load(raw.df, plan)
        ctx.metrics.save(args.name, df)
        profile = GameProfile(name=args.name, platform=args.platform,
                              genre=args.genre, plan=plan)
        from gaa.core.crawl.roblox_title import universe_id_from, lookup_universe_title
        if getattr(profile, "title", None) is None and profile.platform == "roblox":
            uid = universe_id_from(profile.name)
            if uid:
                profile.title = lookup_universe_title(uid)
        ctx.profiles.save(profile)
        ctx.profiles.set_active(args.name)
    except IngestError as e:
        return e.as_dict()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "ingest_failed", "detail": str(exc),
                "hint": "could not ingest the data with this plan"}
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
