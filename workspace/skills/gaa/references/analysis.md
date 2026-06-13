# Analysis (golden path)

Start (fast ack — `--budget` caps the first call so you can reply immediately):

    gaa analyze "<user question, verbatim>" --budget 2

Returns `{run_id, status, stage, done}`. Reply in one sentence and end with `[[gaa:run_id=<run_id>]]`.

Advance / inspect (the web UI usually does this; in pure chat, loop a few times):

    gaa step <run_id>       # advance one slice; returns {stage, status, done}
    gaa status <run_id>     # READ ONLY — never advances; {status, stage, done, ledger_count, report_path}
    gaa jobs                # list runs (run_id, status, stage, query) — use to recover a run id

When `done`, the dossier is on disk at the run's `report_path`/`summary_path`. Relay the summary;
the web UI renders the HTML. Never fabricate a run id — if unsure, `gaa jobs`.
