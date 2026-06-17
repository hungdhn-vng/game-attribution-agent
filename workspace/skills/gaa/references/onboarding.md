# Onboarding & profiles

Connect a game's data. The agent accepts **CSV/TSV, Excel (.xlsx), JSON/JSONL, or a table
pasted straight into chat**, in either wide (one column per metric) or long layout. Unknown
metrics/dimensions are **kept** (not dropped). Two steps, confidence-gated.

## Step 1 — propose a plan

    onboard_propose(content_b64=<base64 file>, filename="data.xlsx")   # a file
    onboard_propose(text="| date | dau | ... |")                       # a pasted table
    onboard_propose(csv="<path>")                                      # a local path

Returns `{plan, summary, preview, confidence, auto_ok}`.

## Step 2 — confidence gate

- If `auto_ok` is **true** (high confidence, no caveats): call `onboard_confirm` right away,
  then tell the user what you read — format, layout, which columns mapped to canonical names,
  which were kept as custom metrics/dims, and the row count.
- If `auto_ok` is **false** (or `plan.notes` flags anything): show the user `summary` + `preview`
  and ask them to confirm or correct the mapping before you call `onboard_confirm`.

## Step 3 — confirm (ingest)

    onboard_confirm(plan=<the plan JSON, possibly edited>, name="<game>",
                    platform=<roblox|steam|...>, genre="<genre>",
                    content_b64=<same file> | text=<same paste> | csv=<same path>)

On error the tool returns `{status:"error", error:<code>, detail, hint}` — relay the `hint`
to the user (e.g. `unreadable_file`, `no_table_found`, `cannot_interpret`, `plan_mismatch`,
`bad_values`).

## Profiles

    profile_list            # {profiles[], active}
    profile_use <name>      # switch the active game
