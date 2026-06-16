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


def _p1_surprise_scan(ctx: AnalysisContext, covered: set[tuple[str, str]]) -> list[_Candidate]:
    """For every metric × dimension NOT already covered by a targeted module, run
    Adtributor between the window endpoints and emit its surprising elements."""
    out: list[_Candidate] = []
    for metric in sorted(ctx.metrics["metric"].unique()):
        dfm = ctx.metrics[ctx.metrics["metric"] == metric]
        s, e = _two_dates(dfm, ctx.start, ctx.end)
        if s is None:
            continue
        for dim in CANONICAL_DIMS:
            if (metric, dim) in covered:
                continue
            if dim not in dfm.columns or dfm[dim].isna().all():
                continue
            sub = dfm[~is_aggregate_label(dfm[dim])]
            forecast = sub[sub["date"] == s].groupby(dim)["value"].sum().to_dict()
            actual = sub[sub["date"] == e].groupby(dim)["value"].sum().to_dict()
            if not forecast or not actual:
                continue
            res = adtributor_dimension(forecast, actual)
            # Elements can carry low EP (adtributor selects by surprise); the |ep|<0.1 gate below drops noise.
            for el in res["elements"]:
                ep, sur = el["ep"], el["surprise"]
                if abs(ep) < 0.1:
                    continue
                out.append(_Candidate(
                    score=abs(ep) * (1.0 + sur),
                    strength=_strength(ep),
                    claim=f"{dim}={el['key']} drove {ep * 100:.0f}% of the {metric} move (unprompted)",
                    value=f"EP {ep * 100:.0f}% · surprise {sur:.3f}",
                    source=f"internal:{metric} by {dim} (exploration/Adtributor)",
                    timeframe=f"{s.date()}..{e.date()}",
                    dedup_key=(metric, dim, str(el["key"])),
                ))
    return out


def _marg_surprise(dfm: pd.DataFrame, dim: str, s, e) -> float:
    sub = dfm[~is_aggregate_label(dfm[dim])]
    f = sub[sub["date"] == s].groupby(dim)["value"].sum().to_dict()
    a = sub[sub["date"] == e].groupby(dim)["value"].sum().to_dict()
    return adtributor_dimension(f, a)["surprise"] if f and a else 0.0


def _p2_interaction(ctx: AnalysisContext) -> list[_Candidate]:
    """Find the dimension-pair CELL whose delta is not explained by additive main effects
    (two-way ANOVA-style interaction residual on the start->end delta matrix)."""
    metric = ctx.metric
    if not metric:
        return []
    dfm = ctx.metrics[ctx.metrics["metric"] == metric]
    s, e = _two_dates(dfm, ctx.start, ctx.end)
    if s is None:
        return []
    dims = [d for d in CANONICAL_DIMS
            if d in dfm.columns and not dfm[d].isna().all() and dfm[d].nunique() >= 2]
    dims = sorted(dims, key=lambda d: _marg_surprise(dfm, d, s, e), reverse=True)[:3]
    out: list[_Candidate] = []
    for da, db in itertools.combinations(dims, 2):
        sub = dfm[~is_aggregate_label(dfm[da]) & ~is_aggregate_label(dfm[db])]
        f = sub[sub["date"] == s].groupby([da, db])["value"].sum()
        a = sub[sub["date"] == e].groupby([da, db])["value"].sum()
        cells = a.index.union(f.index)
        delta = {c: float(a.get(c, 0.0)) - float(f.get(c, 0.0)) for c in cells}
        if len(delta) < 2:
            continue
        keys_a = sorted({c[0] for c in delta})
        keys_b = sorted({c[1] for c in delta})
        grand = _mean(list(delta.values()))
        row_mean = {ka: _mean([delta.get((ka, kb), 0.0) for kb in keys_b]) for ka in keys_a}
        col_mean = {kb: _mean([delta.get((ka, kb), 0.0) for ka in keys_a]) for kb in keys_b}
        # Normalize by total absolute activity (not net total): the net can be ~0 when
        # cells compensate (a "shift" pattern), which would otherwise blow scores up.
        abs_total = sum(abs(v) for v in delta.values())
        denom = abs_total if abs_total > 1e-9 else 1e-9
        best = None
        for (ka, kb), d in delta.items():
            resid = d - (row_mean[ka] + col_mean[kb] - grand)
            score = abs(resid) / denom
            # Tie-break by absolute delta magnitude so the actual mover wins over zero-delta cells.
            if best is None or score > best[0] or (score == best[0] and abs(d) > abs(best[3])):
                best = (score, ka, kb, d, resid)
        if best and best[0] >= 0.2:
            score, ka, kb, d, resid = best
            out.append(_Candidate(
                score=score,
                strength=_strength(score),
                claim=(f"{metric} move concentrates in {da}={ka} × {db}={kb} "
                       f"beyond what {da} or {db} explain alone"),
                value=f"cell Δ {d:+.0f} · interaction residual {resid:+.0f}",
                source=f"internal:{metric} by {da}×{db} (exploration/interaction)",
                timeframe=f"{s.date()}..{e.date()}",
                dedup_key=(metric, f"{da}×{db}", f"{ka}×{kb}"),
            ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out
