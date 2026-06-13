"""GAA Custom Agent HTTP server (FastAPI on :8080).

Exposes create_app() — the production entrypoint is `gaa.server.app:app`.

Note: create_app is imported lazily so that submodules (persona, capabilities,
etc.) can be imported independently during tests before gaa.server.app exists.
"""
from __future__ import annotations


def __getattr__(name: str):
    if name == "create_app":
        from gaa.server.app import create_app  # noqa: PLC0415
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["create_app"]
