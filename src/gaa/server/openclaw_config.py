"""Render OpenClaw's openclaw.json wiring MaaS + the GAA MCP server. Secrets stay as
${ENV} refs (OpenClaw substitutes at load). Shape validated live in Phase A spike:
mcp.servers at top level, gateway with http endpoints + token auth, models.mode merge."""
from __future__ import annotations

import json


def render_config(*, model: str = "google/gemma-4-31b-it") -> str:
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
        "agents": {"defaults": {"model": {"primary": f"maas/{model}"}}},
        "mcp": {
            "servers": {
                "gaa": {
                    "command": "python3",
                    "args": ["-m", "gaa.mcp.server"],
                }
            }
        },
    }
    return json.dumps(cfg, indent=2)
