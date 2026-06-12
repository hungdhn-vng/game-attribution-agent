import os
from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, RequestContext, PingStatus

import gaa as _gaa
from gaa.config import Settings
from gaa.llm.client import LangChainMaaSLLM
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.store.benchmark_store import BenchmarkStore
from gaa.store.benchmark_seed import seed_benchmark_store
from gaa.onboarding.profiler import Profiler
from gaa.sources.crawling_benchmark import CrawlingBenchmarkSource
from gaa.admin_actions import AdminActions
from gaa.store.config_store import ConfigStore
from gaa.sources.dynamic import DynamicRefresher, DynamicSignals
from gaa.synth.synthesizer import Synthesizer
from gaa.jobs.job_store import JobStore
from gaa.jobs.pipeline import AnalysisPipeline
from gaa.graph import GraphAgent

load_dotenv()
app = GreenNodeAgentBaseApp()

settings = Settings()

# ── Shared stores (constructed once; pipeline + agent share the same instances) ──
_profile_store = ProfileStore(settings.db_path)
_metrics_store = MetricsStore(settings.cache_dir + "/metrics")

# ── Benchmark store — seed from bundled snapshot on every cold start ──────────
_benchmark_store = BenchmarkStore(settings.cache_dir + "/benchmark.sqlite")
_snapshot_path = os.path.join(
    os.path.dirname(_gaa.__file__), "data", "seed", "benchmark_snapshot.json"
)
seed_benchmark_store(_benchmark_store, _snapshot_path)
_benchmark = CrawlingBenchmarkSource(_benchmark_store)

# ── Runtime config + dynamic sources (admin-changeable, no restart needed) ───
_config = ConfigStore(settings.db_path)
_refresher = DynamicRefresher(config=_config, settings=settings, store=_benchmark_store)
_signals = DynamicSignals(config=_config, settings=settings)

# ── LLM clients ───────────────────────────────────────────────────────────────
_llm = LangChainMaaSLLM(settings)
_synth = Synthesizer(
    _llm,
    instructions_provider=lambda: _config.resolve("behavior_instructions")[0],
)

# ── Pipeline + job store ──────────────────────────────────────────────────────
_pipeline = AnalysisPipeline(
    profiles=_profile_store,
    metrics_store=_metrics_store,
    benchmark=_benchmark,
    refresher=_refresher,
    synth=_synth,
    signals=_signals,
    n_samples=int(os.environ.get("GAA_N_SAMPLES", "3")),
)
_jobs = JobStore(settings.cache_dir + "/jobs.sqlite")

# ── Agent — shares the same ProfileStore + MetricsStore as the pipeline ───────
_admin = AdminActions(config=_config, profiles=_profile_store)

_agent = GraphAgent(
    jobs=_jobs,
    pipeline=_pipeline,
    profile_store=_profile_store,
    metrics_store=_metrics_store,
    benchmark=_benchmark,
    profiler=Profiler(_llm),
    request_budget_s=float(os.environ.get("GAA_REQUEST_BUDGET_S", "40")),
    admin=_admin,
)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    try:
        return {"status": "success",
                **_agent.handle(payload, context.session_id, context.user_id)}
    except Exception as exc:  # graceful degradation — never 500 the judge's request
        return {"status": "error", "error": str(exc)}


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
