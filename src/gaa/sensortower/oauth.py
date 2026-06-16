"""OAuth 2.1 (auth-code + PKCE + refresh + DCR) against the Sensor Tower connector.

We drive the dance by hand (not the MCP SDK's inline OAuthClientProvider) because our
login spans multiple chat turns and a real web callback, not one blocking connection.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import urllib.parse as _up

import httpx

from gaa.sensortower import config, store

_log = logging.getLogger(__name__)
_ENDPOINTS_CACHE: dict[str, dict] = {}
_TIMEOUT = 15.0
_REFRESH_MARGIN_S = 60


def endpoints() -> dict:
    if "v" not in _ENDPOINTS_CACHE:
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.get(config.well_known_url())
            r.raise_for_status()
            _ENDPOINTS_CACHE["v"] = r.json()
    return _ENDPOINTS_CACHE["v"]


def ensure_client() -> dict:
    existing = store.get_client()
    if existing and existing.get("client_id"):
        return existing
    body = {
        "client_name": "GAA Sensor Tower Connector",
        "redirect_uris": [config.redirect_uri()],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.post(endpoints()["registration_endpoint"], json=body)
        r.raise_for_status()
        data = r.json()
    rec = {"client_id": data["client_id"],
           "client_secret": data.get("client_secret", ""),
           "expires_at": float(data.get("client_secret_expires_at") or 0)}
    store.set_client(rec)
    return rec


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(session: str, *, now: float) -> str:
    client = ensure_client()
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    store.set_pending(state, {"code_verifier": verifier, "session": session, "ts": now})
    q = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": config.redirect_uri(),
        "scope": "openid",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return endpoints()["authorization_endpoint"] + "?" + _up.urlencode(q)


def _token_request(form: dict) -> dict:
    client = ensure_client()
    form = {**form, "client_id": client["client_id"], "client_secret": client["client_secret"]}
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.post(endpoints()["token_endpoint"], data=form)
        r.raise_for_status()
        return r.json()


def exchange_code(code: str, state: str, *, now: float) -> dict:
    pending = store.pop_pending(state)
    if not pending:
        raise ValueError("unknown or expired state")
    data = _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri(),
        "code_verifier": pending["code_verifier"],
    })
    rec = {"access_token": data["access_token"],
           "refresh_token": data.get("refresh_token", ""),
           "expiry": now + float(data.get("expires_in", 3600)) - _REFRESH_MARGIN_S}
    store.set_tokens(pending["session"], rec)
    return rec


def valid_access_token(session: str, *, now: float) -> str | None:
    rec = store.get_tokens(session)
    if not rec:
        return None
    if now < rec["expiry"]:
        return rec["access_token"]
    if not rec.get("refresh_token"):
        store.clear_tokens(session)
        return None
    try:
        data = _token_request({"grant_type": "refresh_token", "refresh_token": rec["refresh_token"]})
    except httpx.HTTPStatusError as exc:
        # The server gave a definite answer. 400/401 means the refresh token is dead
        # (revoked/expired) → clear so the user reconnects. Other statuses (e.g. 5xx)
        # are transient → keep the token and let the next call retry.
        if exc.response.status_code in (400, 401):
            _log.info("sensor tower refresh rejected (HTTP %d) for session=%s; clearing",
                      exc.response.status_code, session)
            store.clear_tokens(session)
        else:
            _log.info("sensor tower refresh got HTTP %d for session=%s; keeping token for retry",
                      exc.response.status_code, session)
        return None
    except httpx.HTTPError:
        # Transport/timeout error — a network blip is NOT proof the refresh token is dead.
        # Keep it; report "not connected" for now and retry on the next call.
        _log.info("sensor tower refresh transient error for session=%s; keeping token", session)
        return None
    new = {"access_token": data["access_token"],
           "refresh_token": data.get("refresh_token") or rec["refresh_token"],
           "expiry": now + float(data.get("expires_in", 3600)) - _REFRESH_MARGIN_S}
    store.set_tokens(session, new)
    return new["access_token"]
