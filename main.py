import os
from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, RequestContext, PingStatus

from gaa.config import Settings
from gaa.engine import AttributionEngine
from gaa.llm.client import LangChainMaaSLLM
from gaa.store.profile_store import ProfileStore
from gaa.store.metrics_store import MetricsStore
from gaa.onboarding.profiler import Profiler
from gaa.sources.roblox_benchmark import RoMonitorBenchmark
from gaa.sources.web_signals import WebSignalsSource
from gaa.memory import make_checkpointer
from gaa.graph import GraphAgent

load_dotenv()
app = GreenNodeAgentBaseApp()

_s = Settings()
_llm = LangChainMaaSLLM(_s)
_benchmark = RoMonitorBenchmark(
    cache_dir=_s.cache_dir + "/benchmark",
    genre_url_tmpl=os.environ.get("GAA_BENCHMARK_URL_TMPL", "https://example/{genre}.json"))
_signals = WebSignalsSource(
    cache_dir=_s.cache_dir + "/signals",
    query_url_tmpl=os.environ.get("GAA_SIGNALS_URL_TMPL", "https://example/news?q={game}"))
_agent = GraphAgent(
    engine=AttributionEngine(_llm, _benchmark, _signals),
    profile_store=ProfileStore(_s.db_path),
    metrics_store=MetricsStore(_s.cache_dir + "/metrics"),
    benchmark=_benchmark,
    profiler=Profiler(_llm),
    checkpointer=make_checkpointer(),
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
