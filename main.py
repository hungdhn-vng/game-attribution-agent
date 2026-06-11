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
from gaa.sources.web_signals import WebSignalsSource
from gaa.sources.fixtures import FixtureSignalsSource
from gaa.sources.providers.roblox import RobloxBenchmarkProvider
from gaa.sources.providers.steam import SteamBenchmarkProvider
from gaa.sources.providers.web import WebSearchBenchmarkProvider
from gaa.crawl.fetcher import CachedFetcher
from gaa.crawl.perplexity import perplexity_answer
from gaa.crawl.refresher import BenchmarkRefresher
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

# ── Benchmark providers (quant crawl + optional Perplexity web tier) ─────────
_benchmark_mode = os.environ.get("GAA_BENCHMARK_MODE", "")

if _benchmark_mode == "crawl":
    _roblox_fetcher = CachedFetcher(settings.cache_dir + "/benchmark")
    _steam_fetcher = CachedFetcher(settings.cache_dir + "/benchmark")
    _roblox_provider = RobloxBenchmarkProvider(
        fetcher=_roblox_fetcher,
        discover_url_tmpl=os.environ.get("GAA_ROBLOX_DISCOVER_URL_TMPL", ""),
        series_url_tmpl=os.environ.get("GAA_ROBLOX_SERIES_URL_TMPL", ""),
    )
    _steam_provider = SteamBenchmarkProvider(
        fetcher=_steam_fetcher,
        discover_url_tmpl=os.environ.get("GAA_STEAM_DISCOVER_URL_TMPL", ""),
        series_url_tmpl=os.environ.get("GAA_STEAM_SERIES_URL_TMPL", ""),
    )
    _providers_by_platform: dict = {
        "roblox": [_roblox_provider],
        "steam": [_steam_provider],
    }
    _web_provider = (
        WebSearchBenchmarkProvider(
            lambda prompt: perplexity_answer(prompt, settings)
        )
        if settings.perplexity_api_key
        else None
    )
else:
    # Default / demo mode — snapshot floor serves all data; crawl short-circuits.
    _providers_by_platform = {}
    _web_provider = None

_refresher = BenchmarkRefresher(
    store=_benchmark_store,
    providers_by_platform=_providers_by_platform,
    web_provider=_web_provider,
)

# ── Signals source ────────────────────────────────────────────────────────────
_sig_tmpl = os.environ.get("GAA_SIGNALS_URL_TMPL")
_signals = (
    WebSignalsSource(cache_dir=settings.cache_dir + "/signals", query_url_tmpl=_sig_tmpl)
    if _sig_tmpl
    else FixtureSignalsSource([])
)

# ── LLM clients ───────────────────────────────────────────────────────────────
_llm = LangChainMaaSLLM(settings)
_synth = Synthesizer(_llm)

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
_agent = GraphAgent(
    jobs=_jobs,
    pipeline=_pipeline,
    profile_store=_profile_store,
    metrics_store=_metrics_store,
    benchmark=_benchmark,
    profiler=Profiler(_llm),
    request_budget_s=float(os.environ.get("GAA_REQUEST_BUDGET_S", "40")),
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
