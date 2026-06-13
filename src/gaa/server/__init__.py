"""GAA Custom Agent HTTP server (FastAPI on :8080).

Exposes create_app() — the production entrypoint is `gaa.server.app:app`.
"""
from gaa.server.app import create_app

__all__ = ["create_app"]
