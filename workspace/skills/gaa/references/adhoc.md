# Ad-hoc analysis (Tier 3 — when no built-in command fits)

Write a SHORT Python script and run it with your exec tool. Use the `gaa.lab` API — it is the
ONLY sanctioned way to touch the data, and it is READ-ONLY (you cannot modify the stores).

    from gaa import lab
    rid = lab.run_id()                       # the run you're working on (set for you)
    st  = lab.run_state(rid)                 # {metric, start, end, genre, platform, profile_name, ...} (a copy)
    df  = lab.load_metrics(st["profile_name"])           # canonical metrics DataFrame (a copy)
    bench = lab.load_benchmark(st["genre"], st["platform"], st["start"], st["end"])  # genre trend (a copy)
    # ... your calculation ...
    lab.add_evidence(rid, claim="weekend ARPU is 2.1x weekday", value="2.1x", source="scratch/01-arpu.py")

Save scripts under the run's scratch dir: `gaa` exposes it as `lab.scratch_dir(rid)`
(-> `runs/<id>/scratch/`). Conventions you MUST follow:
- **Print every number you intend to report, and quote it verbatim. Never report a number the
  script did not print.**
- Ad-hoc evidence is automatically capped at Moderate strength — that's expected; deterministic
  modules outrank one-shot code.
- Never write to the data stores; `lab` loaders return copies on purpose.

After it runs, `gaa synth --run <id> "<question>"` folds the new evidence into the dossier.
