from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import gaa as _gaa
from gaa.core.settings import Settings
from gaa.core.llm.client import LangChainMaaSLLM
from gaa.core.onboarding.profiler import Profiler
from gaa.core.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.core.sources.dynamic import DynamicRefresher, DynamicSignals
from gaa.core.store.benchmark_seed import seed_benchmark_store
from gaa.core.store.benchmark_store import BenchmarkStore
from gaa.core.store.config_store import ConfigStore
from gaa.core.store.metrics_store import MetricsStore
from gaa.core.store.profile_store import ProfileStore
from gaa.core.synth.synthesizer import Synthesizer
from gaa.runs.pipeline import AnalysisPipeline
from gaa.runs.store import RunStore


@dataclass
class GaaContext:
    settings: Settings
    profiles: ProfileStore
    metrics: MetricsStore
    config: ConfigStore
    benchmark: CrawlingBenchmarkSource
    profiler: Profiler
    pipeline: AnalysisPipeline
    runs: RunStore
    step_budget_s: float


def build_context(llm: Optional[Any] = None, today: Optional[str] = None) -> GaaContext:
    """Construct every store/source/client once and wire the pipeline.

    ``llm`` defaults to the real MaaS client; tests pass a ``FakeLLM``.
    ``today`` is forwarded to the RunStore for deterministic run ids in tests.
    """
    settings = Settings()

    profiles = ProfileStore(settings.db_path)
    metrics = MetricsStore(settings.cache_dir + "/metrics")

    benchmark_store = BenchmarkStore(settings.cache_dir + "/benchmark.sqlite")
    snapshot_path = os.path.join(
        os.path.dirname(_gaa.__file__), "data", "seed", "benchmark_snapshot.json"
    )
    if os.path.exists(snapshot_path):
        seed_benchmark_store(benchmark_store, snapshot_path)
    benchmark = CrawlingBenchmarkSource(benchmark_store)

    config = ConfigStore(settings.db_path)
    # DynamicRefresher takes (config, settings, store); DynamicSignals takes (config, settings)
    refresher = DynamicRefresher(config=config, settings=settings, store=benchmark_store)
    signals = DynamicSignals(config=config, settings=settings)

    if llm is None:
        llm = LangChainMaaSLLM(settings)
    synth = Synthesizer(llm, instructions_provider=lambda: config.resolve("behavior_instructions")[0])

    # AnalysisPipeline positional signature: profiles, metrics_store, benchmark,
    # refresher, synth, signals, n_samples=3  — using keyword args for clarity.
    pipeline = AnalysisPipeline(
        profiles=profiles,
        metrics_store=metrics,
        benchmark=benchmark,
        refresher=refresher,
        synth=synth,
        signals=signals,
        n_samples=int(os.environ.get("GAA_N_SAMPLES", "3")),
    )
    runs = RunStore(settings.cache_dir + "/runs", today=today)

    return GaaContext(
        settings=settings,
        profiles=profiles,
        metrics=metrics,
        config=config,
        benchmark=benchmark,
        profiler=Profiler(llm),
        pipeline=pipeline,
        runs=runs,
        step_budget_s=float(os.environ.get("GAA_STEP_BUDGET_S", "20")),
    )
