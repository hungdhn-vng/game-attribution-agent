from dataclasses import dataclass
from typing import Optional
import pandas as pd

from gaa.schema.profile import GameProfile
from gaa.schema.ledger import EvidenceLedger
from gaa.schema.hypothesis import AttributionHypothesis
from gaa.modules.base import AnalysisContext
from gaa.modules.anomaly import AnomalyDetection
from gaa.modules.segment import SegmentDecomposition
from gaa.modules.market_benchmark import MarketBenchmark
from gaa.modules.competitor_signals import CompetitorSignals
from gaa.synth.synthesizer import Synthesizer
from gaa.synth.validator import validate_citations
from gaa.synth.gate import apply_gate
from gaa.synth.concurrent import sample_concurrently
from gaa.orchestrator.planner import parse_query
from gaa.llm.client import LLM
from gaa.sources.base import BenchmarkSource, SignalsSource


@dataclass
class AnalysisResult:
    hypothesis: AttributionHypothesis
    metric: Optional[str]
    start: Optional[str]
    end: Optional[str]


class AttributionEngine:
    def __init__(self, llm: LLM, benchmark: BenchmarkSource, signals: SignalsSource,
                 n_samples: int = 3) -> None:
        self._synth = Synthesizer(llm)
        self._benchmark = benchmark
        self._signals = signals
        self._n = n_samples

    def _run(self, profile: GameProfile, metrics: pd.DataFrame, query: str):
        parsed = parse_query(query)
        ctx = AnalysisContext(profile=profile, metrics=metrics, query=query,
                              metric=parsed["metric"], direction=parsed["direction"])
        ledger = EvidenceLedger()
        # order matters: anomaly resolves metric/window (incl. scan mode + change-point) first
        AnomalyDetection().run(ctx, ledger)
        SegmentDecomposition().run(ctx, ledger)
        MarketBenchmark(self._benchmark).run(ctx, ledger)
        CompetitorSignals(self._signals).run(ctx, ledger)
        # self-consistency: sample N times concurrently, gate, then enforce citations
        samples = sample_concurrently(self._synth, ledger, query, self._n)
        if not samples:
            samples = [self._synth.synthesize(ledger, query)]
        hyp = apply_gate(samples[0], samples)
        hyp = validate_citations(hyp, ledger)
        return hyp, ctx

    def analyze(self, profile: GameProfile, metrics: pd.DataFrame,
                query: str) -> AttributionHypothesis:
        return self._run(profile, metrics, query)[0]

    def analyze_full(self, profile: GameProfile, metrics: pd.DataFrame,
                     query: str) -> AnalysisResult:
        hyp, ctx = self._run(profile, metrics, query)
        return AnalysisResult(hypothesis=hyp, metric=ctx.metric, start=ctx.start, end=ctx.end)
