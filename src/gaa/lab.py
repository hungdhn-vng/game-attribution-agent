"""Sanctioned read-only data API + evidence sink for ad-hoc analysis (Tier 3).

Scripts — hand-written scratch code, or promoted tools run via `gaa tools run` —
import this to read a run's data and append evidence. All loaders return COPIES,
so a script can never mutate the stores. Evidence added here is capped at Moderate
strength and tagged by provenance: one-shot generated code must not outrank the
reviewed deterministic modules in a cited dossier.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from gaa.core.settings import Settings
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.runs.store import RunStore, RunBusy

_STRENGTH_CAP = {"high": "med", "med": "med", "low": "low"}


def _settings() -> Settings:
    return Settings()


def _runs() -> RunStore:
    return RunStore(_settings().cache_dir + "/runs")


def run_id() -> Optional[str]:
    """The run this script operates on (from GAA_RUN_ID), or None."""
    return os.environ.get("GAA_RUN_ID") or None


def args() -> dict:
    """Parsed GAA_TOOL_ARGS JSON (for promoted tools), or {} if unset/empty."""
    raw = os.environ.get("GAA_TOOL_ARGS", "").strip()
    return json.loads(raw) if raw else {}


def run_state(rid: str) -> dict:
    """A COPY of the run's persisted plan-state."""
    run = _runs().get(rid)
    if run is None:
        raise ValueError(f"unknown run: {rid!r}")
    return dict(run.state)


def load_metrics(game: str):
    """A COPY of the canonical long-format metrics DataFrame for a game."""
    return MetricsStore(_settings().cache_dir + "/metrics").load(game).copy()


def load_benchmark(genre: str, platform: str, start: str, end: str) -> dict:
    """A COPY of the genre benchmark trend (indexed to 100 over the window)."""
    src = CrawlingBenchmarkSource(BenchmarkStore(_settings().cache_dir + "/benchmark.sqlite"))
    src.set_platform(platform)
    return dict(src.genre_trend(genre, start, end))


def scratch_dir(rid: str) -> Path:
    """The sanctioned (created) scratch directory for a run: runs/<id>/scratch/."""
    d = _runs().path_for(rid) / "scratch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_evidence(rid: str, *, claim: str, value: str, source: str,
                 strength: str = "med", source_type: str = "derived",
                 timeframe: Optional[str] = None) -> str:
    """Append one ledger entry to a run, under the run's lock.

    Strength is capped at Moderate ("med"). The entry's `module` is tagged
    "tool:<name>" when run via `gaa tools run` (GAA_TOOL_NAME set), else "adhoc".
    Returns the new entry id.
    """
    runs = _runs()
    tool = os.environ.get("GAA_TOOL_NAME", "").strip()
    module = f"tool:{tool}" if tool else "adhoc"
    capped = _STRENGTH_CAP.get(strength, "med")
    try:
        with runs.locked(rid):
            run = runs.get(rid)
            if run is None:
                raise ValueError(f"unknown run: {rid!r}")
            ledger = EvidenceLedger()
            ledger.load(run.state.get("ledger", []))
            eid = ledger.add(module=module, claim=claim, value=value, source=source,
                             source_type=source_type, strength=capped, timeframe=timeframe)
            run.state["ledger"] = [e.model_dump() for e in ledger.all()]
            run.add_activity(module, f"ad-hoc evidence: {claim[:60]}")
            runs.save(run)
    except RunBusy as exc:
        raise RuntimeError(f"run {rid!r} is busy (an analysis step is in progress) — retry shortly") from exc
    return eid
