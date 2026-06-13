"""Onboarding propose/confirm tests for GraphAgent — unchanged behaviour."""
import os

from gaa.graph import GraphAgent
from gaa.jobs.job_store import JobStore
from gaa.jobs.pipeline import AnalysisPipeline
from gaa.llm.client import FakeLLM
from gaa.sources.fixtures import FixtureBenchmarkSource, FixtureSignalsSource
from gaa.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.store.benchmark_store import BenchmarkStore
from gaa.crawl.refresher import BenchmarkRefresher
from gaa.onboarding.profiler import Profiler
from gaa.synth.synthesizer import Synthesizer


def _agent(tmp_path):
    tmp = str(tmp_path)
    llm = FakeLLM({"date_col": "Date", "metric_cols": {"DAU": "dau"},
                   "dim_cols": {"Country": "region"}})
    bstore = BenchmarkStore(os.path.join(tmp, "bench.db"))
    benchmark = CrawlingBenchmarkSource(bstore)
    refresher = BenchmarkRefresher(bstore, providers_by_platform={}, web_provider=None)
    synth_llm = FakeLLM({"main_story": "", "causes": {"internal": [], "market": []},
                          "scenarios": [], "risks": [], "assumptions_and_gaps": []})
    synth = Synthesizer(synth_llm)
    ps = ProfileStore(os.path.join(tmp, "p.sqlite"))
    ms = MetricsStore(os.path.join(tmp, "m"))
    pipeline = AnalysisPipeline(
        profiles=ps,
        metrics_store=ms,
        benchmark=benchmark,
        refresher=refresher,
        synth=synth,
        signals=FixtureSignalsSource([]),
        n_samples=1,
    )
    jobs = JobStore(os.path.join(tmp, "jobs.db"))
    return GraphAgent(
        jobs=jobs,
        pipeline=pipeline,
        profile_store=ps,
        metrics_store=ms,
        benchmark=benchmark,
        profiler=Profiler(llm),
    )


def test_onboard_propose_then_confirm(tmp_path):
    agent = _agent(tmp_path)
    p = agent.handle({"action": "onboard_propose", "adapter": "csv",
                      "csv_path": "src/gaa/data/sample/roblox_export.csv"},
                     session_id="s", user_id="u")
    assert p["mode"] == "setup" and p["mapping"]["date_col"] == "Date"

    c = agent.handle({"action": "onboard_confirm", "name": "MyGame", "platform": "roblox",
                      "genre": "survival", "adapter": "csv",
                      "csv_path": "src/gaa/data/sample/roblox_export.csv",
                      "mapping": {"date_col": "Date", "metric_cols": {"DAU": "dau"}, "dim_cols": {}}},
                     session_id="s", user_id="u")
    assert c["mode"] == "setup" and c["row_count"] == 6


def test_onboard_via_inline_csv_data(tmp_path):
    # Browser upload path: the payload carries raw CSV text (csv_data) instead of a
    # server-side csv_path, so any team can onboard their own file with no file on the box.
    agent = _agent(tmp_path)
    csv = "Date,DAU,Country\n2026-05-01,100,SEA\n2026-05-02,90,SEA\n"

    p = agent.handle({"action": "onboard_propose", "adapter": "csv", "csv_data": csv},
                     session_id="s", user_id="u")
    assert p["mode"] == "setup" and p["mapping"]["date_col"] == "Date"

    c = agent.handle({"action": "onboard_confirm", "name": "Inline", "platform": "custom",
                      "genre": "survival", "adapter": "csv", "csv_data": csv,
                      "mapping": {"date_col": "Date", "metric_cols": {"DAU": "dau"}, "dim_cols": {}}},
                     session_id="s", user_id="u")
    assert c["mode"] == "setup" and c["row_count"] == 2
