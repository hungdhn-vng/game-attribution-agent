"""Build a budget-guarded Sensor Tower request from the LLM's loose args: resolve app-IDs,
fill the heavy defaults, and estimate+cap data points (apps × countries × devices × dates ×
bundles) so a single query can't drain the shared monthly allowance."""
from __future__ import annotations

from datetime import date, timedelta

_CAP = 50_000
_MAX_APPS = 10
_MAX_COUNTRIES = 5
_DEFAULT_RANGE_DAYS = 90

# our tool key -> (ST tool name, id param, default devices, default granularity, default bundle, unified?)
_TOOLS = {
    "st_app_performance": ("app_performance_api_v2_app_performance_get", "app_id",
                           ["ios-all", "android-all"], "monthly", "download_revenue", False),
    "st_unified_app_performance": ("unified_app_performance_api_v2_unified_app_performance_g",
                                   "unified_app_id", ["all"], "monthly", "download_revenue", True),
    "st_download_channel": ("download_channel_api_v2_download_channel_get", "app_id",
                            ["ios-all", "android-all"], "monthly", "download_channel", False),
    "st_app_store": ("app_store_api_v2_app_store_get", "app_id",
                     ["ios-all", "android-all"], "daily", "ranks", False),
    "st_search_optimization": ("search_optimization_api_v2_search_optimization_get", "app_id",
                               ["ios-phone", "android-phone"], "daily", "keywords", False),
}
_GRAN_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}
_COARSER = {"daily": "weekly", "weekly": "monthly", "monthly": "quarterly"}


def _date_count(start: str, end: str, gran: str) -> int:
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except (TypeError, ValueError):
        days = 1
    return max(1, days // _GRAN_DAYS.get(gran, 30))


def _estimate(p: dict, id_param: str, gran: str) -> int:
    apps = max(1, len(p.get(id_param) or [1]))
    return (apps * max(1, len(p["countries"])) * max(1, len(p["devices"]))
            * _date_count(p["start_date"], p["end_date"], gran) * 1)


def _note(lst, item):
    if item not in lst:
        lst.append(item)


def build(tool_key: str, args: dict, *, resolver, today: str) -> dict:
    st_tool, id_param, dft_devices, dft_gran, dft_bundle, unified = _TOOLS[tool_key]

    ids = list(args.get("app_ids") or [])
    unresolved = []
    for label in args.get("labels") or []:
        rec = resolver(label)
        if rec:
            ids.append(rec["id"])
        else:
            unresolved.append(label)
    if unresolved:
        return {"status": "error", "error": "need_app_id", "labels": unresolved}
    ids = list(dict.fromkeys(ids))[:_MAX_APPS]

    end = args.get("end_date") or today
    if args.get("start_date"):
        start = args["start_date"]
    else:
        start = (date.fromisoformat(end) - timedelta(days=_DEFAULT_RANGE_DAYS)).isoformat()

    countries = (args.get("countries") or ["US"])[:_MAX_COUNTRIES]
    trimmed = []
    if args.get("countries") and len(args["countries"]) > _MAX_COUNTRIES:
        _note(trimmed, "countries")

    params = {
        id_param: ids,
        "start_date": start, "end_date": end,
        "countries": countries,
        "devices": list(dft_devices),
        "granularity": dft_gran,
        "bundles": [dft_bundle],
        "metrics": args.get("metrics") or [],
    }
    if tool_key == "st_search_optimization" and args.get("keyword"):
        params["keyword"] = args["keyword"]

    gran = params["granularity"]
    while _estimate(params, id_param, gran) > _CAP:
        if len(params["countries"]) > 1:
            params["countries"] = params["countries"][: max(1, len(params["countries"]) // 2)]
            _note(trimmed, "countries")
        elif _date_count(params["start_date"], params["end_date"], gran) > 2:
            params["start_date"] = (date.fromisoformat(params["end_date"]) - timedelta(days=30)).isoformat()
            _note(trimmed, "date_range")
        elif gran in _COARSER:
            gran = params["granularity"] = _COARSER[gran]
            _note(trimmed, "granularity")
        elif len(params[id_param]) > 1:
            params[id_param] = params[id_param][:-1]
            _note(trimmed, "apps")
        else:
            break

    out = {"built": {"st_tool": st_tool, "params": params}}
    if trimmed:
        out["scope_trimmed"] = trimmed
    return out
