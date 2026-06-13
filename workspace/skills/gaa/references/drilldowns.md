# Drilldowns (follow-ups on an existing run)

Each appends evidence to the run's ledger, then re-synthesize + re-render to update the dossier.

    gaa detect   --run <id> [--metric <m>]      # change-point / anomaly (optionally re-point the metric)
    gaa segments --run <id> [--dimension <d>]   # which segment drove it (region/version/cohort/device/source)
    gaa market   --run <id>                      # counterfactual vs the genre
    gaa signals  --run <id>                      # competitor/event signals in the window
    gaa synth    --run <id> "<follow-up question>"   # fresh hypothesis from the enriched ledger
    gaa report   --run <id>                      # re-render the dossier (writes report.html + summary.md)

Typical follow-up: `gaa segments --run <id> --dimension region` -> `gaa synth --run <id> "was it SEA?"`
-> `gaa report --run <id>`. Then relay the new summary.
