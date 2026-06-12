"""Admin actions on /invocations, guarded by a payload `admin_key`.

The key travels in the payload (not a header) because the AgentBase SDK does not
guarantee arbitrary header passthrough to the handler. Comparison is constant-time.
With GAA_ADMIN_KEY unset, every admin action is refused.

Note: admin_set_config applies keys in order and stops at the first invalid one —
earlier keys in the same request stay applied. The response always returns the
full resolved config, so the caller sees the actual state either way.
"""
import hmac
import os
from typing import Optional

from gaa.store.config_store import ConfigStore
from gaa.store.profile_store import ProfileStore

ADMIN_ACTIONS = {
    "admin_get_config",
    "admin_set_config",
    "admin_set_behavior",
    "list_profiles",
    "set_active_profile",
}

MAX_BEHAVIOR_CHARS = 2000


class AdminActions:
    def __init__(self, config: ConfigStore, profiles: ProfileStore,
                 admin_key: Optional[str] = None) -> None:
        self._config = config
        self._profiles = profiles
        self._admin_key = (admin_key if admin_key is not None
                           else os.environ.get("GAA_ADMIN_KEY", ""))

    def handle(self, action: str, payload: dict) -> dict:
        if not self._admin_key:
            return {"status": "error", "code": 403,
                    "error": "admin actions disabled (GAA_ADMIN_KEY not set)"}
        if not hmac.compare_digest(str(payload.get("admin_key", "")), self._admin_key):
            return {"status": "error", "code": 403, "error": "not authorized"}
        try:
            return getattr(self, f"_{action}")(payload)
        except (KeyError, ValueError) as exc:
            return {"status": "error", "error": str(exc)}

    def _admin_get_config(self, payload: dict) -> dict:
        return {"status": "success", "mode": "admin",
                "config": self._config.all_resolved()}

    def _admin_set_config(self, payload: dict) -> dict:
        changes = payload.get("config")
        if not isinstance(changes, dict) or not changes:
            return {"status": "error",
                    "error": "payload must include a non-empty `config` object"}
        for name, value in changes.items():
            self._config.set(name, value)
        return {"status": "success", "mode": "admin",
                "config": self._config.all_resolved()}

    def _admin_set_behavior(self, payload: dict) -> dict:
        text = str(payload.get("instructions", "")).strip()
        if len(text) > MAX_BEHAVIOR_CHARS:
            return {"status": "error",
                    "error": f"instructions too long ({len(text)} > {MAX_BEHAVIOR_CHARS} chars)"}
        self._config.set("behavior_instructions", text or None)
        return {"status": "success", "mode": "admin", "behavior_instructions": text}

    def _list_profiles(self, payload: dict) -> dict:
        active = self._profiles.get_active()
        return {"status": "success", "mode": "admin",
                "profiles": self._profiles.list_names(),
                "active": active.name if active else None}

    def _set_active_profile(self, payload: dict) -> dict:
        name = str(payload.get("name", ""))
        if name not in self._profiles.list_names():
            return {"status": "error", "error": f"unknown profile: {name!r}"}
        self._profiles.set_active(name)
        return {"status": "success", "mode": "admin", "active": name}
