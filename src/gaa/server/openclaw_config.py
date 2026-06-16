"""Render OpenClaw's openclaw.json wiring MaaS + the GAA MCP server. Secrets stay as
${ENV} refs (OpenClaw substitutes at load). Shape validated live in Phase A spike:
mcp.servers at top level, gateway with http endpoints + token auth, models.mode merge."""
from __future__ import annotations

import json
import os


def render_config(*, model: str = "google/gemma-4-31b-it", profile: str = "nonadmin") -> str:
    is_admin = (profile == "admin")
    cfg = {
        "gateway": {
            "mode": "local",
            "auth": {"mode": "token", "token": "${OPENCLAW_GATEWAY_TOKEN}"},
            "http": {
                "endpoints": {
                    "chatCompletions": {"enabled": True},
                    "responses": {"enabled": True},
                }
            },
        },
        "models": {
            "mode": "merge",
            "providers": {
                "maas": {
                    "api": "openai-completions",
                    "baseUrl": "${LLM_BASE_URL}",
                    "apiKey": "${LLM_API_KEY}",
                    "models": [
                        {
                            "id": model,
                            "name": model,
                            "reasoning": False,
                            "input": ["text"],
                            "contextWindow": 128000,
                            "maxTokens": 8192,
                        }
                    ],
                }
            },
        },
        "agents": {"defaults": {"model": {"primary": f"maas/{model}"}, "workspace": os.environ.get("OPENCLAW_WORKSPACE", "/home/node/.openclaw/workspace")}},
        "mcp": {
            "servers": {
                "gaa": {
                    "command": "python3",
                    "args": ["-m", "gaa.mcp.server"],
                    "env": {
                        "GAA_DB_PATH": "${GAA_DB_PATH}",
                        "GAA_CACHE_DIR": "${GAA_CACHE_DIR}",
                        "GAA_RUN_SIDECAR": "${GAA_RUN_SIDECAR}",
                        "GAA_PROGRESS": "${GAA_PROGRESS}",
                        "GAA_MCP_ADMIN": "1" if is_admin else "0",
                        "LLM_BASE_URL": "${LLM_BASE_URL}",
                        "LLM_API_KEY": "${LLM_API_KEY}",
                        "LLM_MODEL": "${LLM_MODEL}",
                        "VSTORAGE_ENDPOINT": "${VSTORAGE_ENDPOINT}",
                        "VSTORAGE_BUCKET": "${VSTORAGE_BUCKET}",
                        "VSTORAGE_ACCESS_KEY": "${VSTORAGE_ACCESS_KEY}",
                        "VSTORAGE_SECRET_KEY": "${VSTORAGE_SECRET_KEY}",
                        "VSTORAGE_REGION": "${VSTORAGE_REGION}",
                    },
                }
            }
        },
    }
    if not is_admin:
        cfg["tools"] = {"allow": ["gaa__*"]}
    return json.dumps(cfg, indent=2)
