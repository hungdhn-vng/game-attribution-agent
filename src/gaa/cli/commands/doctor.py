from __future__ import annotations

import importlib

_REQUIRED_DEPS = [
    "pandas", "pyarrow", "statsmodels", "ruptures", "plotly", "jinja2", "langchain_openai",
]


def cmd_doctor(ctx, args) -> dict:
    """Health check: deps + config + stores are hard (error-level); active
    profile + LLM credentials are warn-level (missing is OK for a fresh setup)."""
    checks: list[dict] = []

    for mod in _REQUIRED_DEPS:
        try:
            importlib.import_module(mod)
            checks.append({"name": f"dep:{mod}", "ok": True, "level": "error", "detail": "importable"})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": f"dep:{mod}", "ok": False, "level": "error", "detail": str(exc)})

    try:
        ctx.config.all_resolved()
        checks.append({"name": "config", "ok": True, "level": "error",
                       "detail": str(ctx.config._path)})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "config", "ok": False, "level": "error", "detail": str(exc)})

    checks.append({"name": "stores", "ok": True, "level": "error", "detail": "ok"})

    active = ctx.profiles.get_active()
    checks.append({"name": "active_profile", "ok": active is not None, "level": "warn",
                   "detail": active.name if active else "none — run `gaa onboard` first"})

    has_key = bool(ctx.settings.llm_api_key)
    checks.append({"name": "llm_credentials", "ok": has_key, "level": "warn",
                   "detail": "set" if has_key else "LLM_API_KEY unset (synthesis will fail)"})

    ok = all(c["ok"] for c in checks if c["level"] == "error")
    return {"status": "success" if ok else "error", "ok": ok, "checks": checks}
