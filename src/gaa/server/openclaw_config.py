"""Render OpenClaw's openclaw.json wiring MaaS + the GAA MCP server. Secrets stay as
${ENV} refs (OpenClaw substitutes at load). Shape per OpenClaw docs (openai-completions
provider) and validated by Spike 1."""
from __future__ import annotations

import json
import os


def render_config(*, model: str = "google/gemma-4-31b-it") -> str:
    cfg = {
        "agents": {"defaults": {
            "model": {"primary": f"maas/{model}"},
            "mcpServers": {"gaa": {
                "command": "python",
                "args": ["-m", "gaa.mcp.server"],
                "env": {"GAA_MCP_ADMIN": "${GAA_MCP_ADMIN}"},
            }},
        }},
        "models": {"providers": {"maas": {
            "api": "openai-completions",
            "baseUrl": "${LLM_BASE_URL}",
            "apiKey": "${LLM_API_KEY}",
            "models": [{"id": model, "name": model, "reasoning": False,
                        "input": ["text"], "contextWindow": 128000, "maxTokens": 8192}],
        }}},
        "gateway": {"bind": os.environ.get("OPENCLAW_GATEWAY_BIND", "loopback")},
    }
    return json.dumps(cfg, indent=2)
