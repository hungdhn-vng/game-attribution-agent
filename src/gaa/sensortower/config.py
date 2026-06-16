"""Where Sensor Tower lives. All values overridable by env for tests/other tiers."""
from __future__ import annotations

import os
from urllib.parse import urlparse

_DEFAULT_BASE = "https://stg-aawp-connector.vnggames.net/sensor-tower-v2"


def base_url() -> str:
    return os.environ.get("GAA_ST_BASE_URL", _DEFAULT_BASE).rstrip("/")


def well_known_url() -> str:
    """RFC 8414 metadata lives at the HOST root with the resource path as suffix."""
    p = urlparse(base_url())
    return f"{p.scheme}://{p.netloc}/.well-known/oauth-authorization-server{p.path}"


def redirect_uri() -> str:
    return os.environ.get("GAA_ST_REDIRECT_URI", "")
