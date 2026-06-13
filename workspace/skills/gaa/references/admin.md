Note: `config get`, `doctor`, `tools list`, and `tools show` are read-only and fine for any session.
The commands below marked admin-only are the WRITE/exec operations that mutate config, workspace state, or execute code.

# Admin: configuration, health, tools (ADMIN SESSIONS ONLY — write/exec ops)

Only run the write/exec operations for admin sessions (see AGENTS.md). For everyone else: refuse
politely and suggest contacting the admin. Never read or reveal the workspace `.env`.

Config (human-editable `gaa-config.toml`; resolution order file -> env -> default; secrets are env-only):

    gaa config get                         # all keys with {value, origin}
    gaa config get <key>                   # one key
    gaa config set benchmark_mode crawl    # valid keys: benchmark_mode (snapshot|crawl),
                                           # roblox_/steam_/signals_ url templates, behavior_instructions
    # (perplexity_api_key is a secret — set it in .env, NOT here; `set` rejects it)

Health:

    gaa doctor                             # deps/config/stores (hard) + active profile/LLM key (warn)

Tools (Tier 2.5 — graduate a proven scratch script into a reusable tool):

    gaa tools promote --run <id> --script <scratch-rel-path> --name <name> --description "<desc>"
    gaa tools run <name> --run <id> [--args '<json>']   # md5-verified before running
    gaa tools list | show <name> | remove <name>
    gaa tools sync-docs                    # regenerate references/tools.md from the registry
