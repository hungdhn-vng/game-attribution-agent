# src/gaa/core/modules/exploration.py
"""Autonomous exploration: mine all metrics × dimensions for high-impact, *unprompted*
findings the targeted modules didn't ask about, rank them, and append the top-N to the
evidence ledger. Deterministic — the LLM only narrates. Implements AnalysisModule;
never raises (per the module contract in base.py)."""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from gaa.core.modules.base import AnalysisContext
from gaa.core.schema.ledger import EvidenceLedger
from gaa.core.schema.canonical import CANONICAL_DIMS
from gaa.core.analytics.adtributor import adtributor_dimension
from gaa.core.analytics.aggregate import is_aggregate_label, metric_series


@dataclass
class _Candidate:
    score: float
    strength: str
    claim: str
    value: str
    source: str
    timeframe: Optional[str]
    dedup_key: tuple


def _strength(effect: float) -> str:
    """Mirror segment.py: |effect|>=0.5 high, >=0.2 med, else low."""
    a = abs(effect)
    return "high" if a >= 0.5 else ("med" if a >= 0.2 else "low")


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


_SEG_SRC_RE = re.compile(r"internal:(?P<metric>[^ ]+) by (?P<dim>\w+) \(Adtributor\)")


def _covered_pairs(ledger: EvidenceLedger) -> set[tuple[str, str]]:
    """(metric, dim) pairs already decomposed by the segment module, parsed from its
    source strings (e.g. 'internal:dau by region (Adtributor)')."""
    pairs: set[tuple[str, str]] = set()
    for e in ledger.all():
        if e.module == "segment":
            m = _SEG_SRC_RE.search(e.source)
            if m:
                pairs.add((m.group("metric"), m.group("dim")))
    return pairs


def _two_dates(df_metric: pd.DataFrame, start: str | None, end: str | None) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Comparison endpoints for a metric subframe: prefer ctx start/end when present in
    the data, else the metric's own first/last date. Returns (None, None) if <2 dates."""
    dates = sorted(pd.Timestamp(d) for d in df_metric["date"].unique())
    if len(dates) < 2:
        return None, None
    s = pd.Timestamp(start) if start else dates[0]
    e = pd.Timestamp(end) if end else dates[-1]
    if s not in dates:
        s = dates[0]
    if e not in dates:
        e = dates[-1]
    return s, e


def _safe(fn, *args) -> list[_Candidate]:
    """Run a probe; never let it raise (module contract). Returns [] on failure."""
    try:
        return fn(*args)
    except Exception:
        return []
