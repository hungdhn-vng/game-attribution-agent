# Spike: Notion API shapes (live recon, 2026-06-16)

Confirmed against the real workspace (integration "01 [HGF] - Discord Sentiments").
Needs a real integration token; do **not** commit it.

## Findings
- Workspace uses the **data-source model**; use `Notion-Version: 2025-09-03`.
- Schema: `GET /v1/data_sources/{id}` (→ `name`, `properties`).
- Rows: `POST /v1/data_sources/{id}/query` (`sorts`/`filter`/`page_size`).
- Search: `POST /v1/search`, `filter.value` ∈ {`page`, `data_source`}.
- Pages/blocks: `GET /v1/pages/{id}`, `GET /v1/blocks/{id}/children` (unchanged).
- Old `2022-06-28` `/databases/{id}/query` → **404** for these IDs.

## Visible data sources
| Role | ID | Name | title / date / text |
|---|---|---|---|
| Builds | `abee2267-021c-4a98-b91b-95d71e2a0cee` | 04_LiveOps Calendar Content | `Event Name` / `Go-live Date` / `Brief` |
| Sentiment | `3590e4e2-3942-8032-8e8e-000bbb4da32a` | 10_Discord Sentiment | `Report` / (none → `created_time`) / `note` |

(The originally-provided builds ID `32b0e4e2…` is **not shared** with the integration.)

## Live behavior verified (2026-06-16)
- `build_updates` → `source: data_source`, items with `title` (event names) + `date`
  (`Go-live Date`). `summary` is often empty because the `Brief` column is blank in
  these rows — expected.
- `user_sentiment` → `source: data_source`, items with `source` (report titles) + `date`
  (from `created_time`, since the data source has no date property). `snippet` is empty
  because the `note` column is blank — **the report content is in the page body.**
- `notion_fetch(<report url>)` → `kind: page`, `text` = the full report body (player
  quotes, suggestions, impact), truncated to 2000 chars. This is the path to the
  substantive sentiment content.

## Re-run

    set -a && . /tmp/notion-test.env && set +a
    export NOTION_BUILDS_DS=abee2267-021c-4a98-b91b-95d71e2a0cee
    export NOTION_SENTIMENT_DS=3590e4e2-3942-8032-8e8e-000bbb4da32a
    .venv/bin/python - <<'PY'
    from gaa.notion import tools
    print(tools.run_tool("build_updates", {"limit": 3}))
    print(tools.run_tool("user_sentiment", {"limit": 3}))
    # drill into a report body:
    item = tools.run_tool("user_sentiment", {"limit": 1})["items"][0]
    print(tools.run_tool("notion_fetch", {"id": item["url"]}))
    PY
