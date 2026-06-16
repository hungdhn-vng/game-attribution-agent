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


def _p3_lead_lag(ctx: AnalysisContext) -> list[_Candidate]:
    """Find other metrics whose series LEADS the target metric (positive lag, strong
    correlation) — a candidate leading indicator. lag>0 means `other` moves first."""
    target = ctx.metric
    metrics = list(ctx.metrics["metric"].unique())
    series = {m: metric_series(ctx.metrics, m) for m in metrics}
    series = {m: s for m, s in series.items() if len(s) >= 5}
    if target not in series:
        return []
    tgt = series[target]
    out: list[_Candidate] = []
    for m, s in series.items():
        if m == target:
            continue
        best = (0.0, 0)  # (corr, lag)
        for lag in range(1, 8):                  # only positive lags: does `m` lead `tgt`?
            shifted = s.shift(lag)               # shifted[t] = m[t-lag]; correlate with tgt[t]
            joined = pd.concat([tgt, shifted], axis=1, join="inner").dropna()
            if len(joined) < 4:
                continue
            c = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            if pd.notna(c) and abs(c) > abs(best[0]):
                best = (float(c), lag)
        corr, lag = best
        if abs(corr) >= 0.7 and lag > 0:
            # Reward lead time: a longer lead = more advance warning = more actionable (intentional).
            out.append(_Candidate(
                score=abs(corr) * (1.0 + lag / 7.0),
                strength=_strength(abs(corr)),
                claim=(f"{m} moves ~{lag}d before {target} (corr {corr:+.2f}) — "
                       f"possible leading indicator"),
                value=f"corr {corr:+.2f} at lag {lag}d",
                source=f"internal:{m}→{target} (exploration/lead-lag)",
                timeframe=None,
                dedup_key=(m, "lead-lag", target),
            ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def _p4_data_quality(ctx: AnalysisContext) -> list[_Candidate]:
    """Cheap reliability caveats: non-positive values and abrupt single-step jumps.
    Always low-strength; these also feed synth's assumptions_and_gaps."""
    out: list[_Candidate] = []
    for m in ctx.metrics["metric"].unique():
        s = metric_series(ctx.metrics, m)
        if s.empty:
            continue
        n_nonpos = int((s <= 0).sum())
        if n_nonpos:
            out.append(_Candidate(
                score=0.05, strength="low",
                claim=f"{m} has {n_nonpos} non-positive value(s) — possible data gap/outlier",
                value=f"{n_nonpos} non-positive points",
                source=f"internal:{m} (exploration/data-quality)",
                timeframe=None, dedup_key=(m, "dq", "nonpos")))
        # inf steps (a jump from/through zero) are dropped here — the zero itself is
        # already flagged by n_nonpos above.
        pct = s.pct_change().abs().replace([float("inf")], pd.NA).dropna()
        max_pct = pct.max()
        if not pct.empty and max_pct >= 5.0:     # >=500% single-step jump
            out.append(_Candidate(
                score=0.05, strength="low",
                claim=f"{m} has an abrupt {max_pct * 100:.0f}% single-step jump — verify data integrity",
                value=f"max step {max_pct * 100:.0f}%",
                source=f"internal:{m} (exploration/data-quality)",
                timeframe=None, dedup_key=(m, "dq", "jump")))
    return out


class ExplorationSweep:
    """Runs the probe battery, ranks candidates, applies the novelty gate + top-N cap,
    and appends findings to the ledger. P4 data-quality caveats are exempt from the cap."""
    name = "exploration"

    def __init__(self, top_n: int = 4, enabled: bool = True) -> None:
        self._top_n = top_n
        self._enabled = enabled

    def run(self, ctx: AnalysisContext, ledger: EvidenceLedger) -> None:
        if not self._enabled:
            return
        try:
            ctx.extras.setdefault("exploration_dropped", 0)
            ctx.extras.setdefault("exploration_kept", 0)
            covered = _covered_pairs(ledger)
            cands = (_safe(_p1_surprise_scan, ctx, covered)
                     + _safe(_p2_interaction, ctx)
                     + _safe(_p3_lead_lag, ctx))
            seen: set[tuple] = set()
            ranked: list[_Candidate] = []
            for c in sorted(cands, key=lambda c: c.score, reverse=True):
                if c.dedup_key in seen:
                    continue
                seen.add(c.dedup_key)
                ranked.append(c)
            kept = ranked[:self._top_n]
            dropped = len(ranked) - len(kept)
            for c in kept:
                ledger.add(module=self.name, claim=c.claim, value=c.value, source=c.source,
                           source_type="derived", strength=c.strength, timeframe=c.timeframe)
            for c in _safe(_p4_data_quality, ctx):   # caveats: always appended, exempt from cap
                ledger.add(module=self.name, claim=c.claim, value=c.value, source=c.source,
                           source_type="derived", strength=c.strength, timeframe=c.timeframe)
            ctx.extras["exploration_dropped"] = dropped
            ctx.extras["exploration_kept"] = len(kept)
        except Exception:
            ledger.add(module=self.name, claim="exploration sweep encountered an error",
                       value="n/a", source="internal", source_type="derived", strength="low")
