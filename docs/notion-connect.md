# Connecting Notion to the GAA agent

The `gaa.notion` MCP server ships in the image but is **inert until connected**.
Connect it once from an **admin** chat session (no redeploy needed). It uses Notion's
data-source API (`Notion-Version: 2025-09-03`).

## Prerequisites
1. In the target Notion workspace, create an **internal integration** and copy its token
   (starts with `ntn_`).
2. **Share** the relevant pages/data sources with the integration (each → `•••` →
   Connections → add your integration). The integration only sees what you share.
3. Note the **data-source IDs** for your Builds and Sentiment data sources (open the
   data source in Notion → `•••` → Copy link → the 32-hex id; or use `notion_search`
   with `type=data_source`).

## Connect (admin chat)

    secret_set notion_token <your-notion-token>
    # optional — point the focused tools at specific data sources:
    secret_set notion_builds_ds <builds-data-source-id>
    secret_set notion_sentiment_ds <sentiment-data-source-id>

    mcp_add name=notion command=python3 args=["-m","gaa.notion.server"] \
      env={"NOTION_TOKEN":"notion_token","NOTION_BUILDS_DS":"notion_builds_ds","NOTION_SENTIMENT_DS":"notion_sentiment_ds"}

A supervised reload re-renders the config, wires the `notion` server, injects the
secrets, and auto-allows `notion__*` in non-admin mode.

## Tools
- `notion__build_updates(since?, until?, query?, limit?)`
- `notion__user_sentiment(since?, until?, query?, limit?)`
- `notion__notion_search(query, type?, limit?)`  — `type` is `page` or `data_source`
- `notion__notion_fetch(id)`  — id or URL of a page or data source

If no Builds/Sentiment data source is configured, the focused tools fall back to
workspace keyword search. **Sentiment report detail lives in the page body** — the
focused tools return the row (title + date + url); call `notion_fetch` on an item's
`url` for the full report text.

## Disconnect / rotate

    mcp_remove notion
    secret_set notion_token <new-token>     # rotate
