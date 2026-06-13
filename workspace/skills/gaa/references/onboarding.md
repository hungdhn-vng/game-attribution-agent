Prefix every command with the workspace+env line from SKILL.md (`cd ~/.openclaw/workspace/gaa && set -a && . ./.env && set +a && …`).

# Onboarding & profiles

Connect a game's data (two steps, human-confirmed mapping). ADMIN sessions only (see AGENTS.md).

    gaa onboard propose --csv <path>            # LLM proposes a column mapping from the first rows
    # show the user the proposed mapping; on confirmation:
    gaa onboard confirm --csv <path> --mapping '<the JSON mapping>' \
        --name "<game>" --platform <roblox|steam|...> --genre "<genre>"

Profiles:

    gaa profile list            # {profiles[], active}
    gaa profile use <name>      # switch the active game
