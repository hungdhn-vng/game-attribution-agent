"""Tests for GraphAgent with the async job-based analyze contract (Task A9a)."""
import os
import pandas as pd
import pytest

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
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.synth.synthesizer import Synthesizer


_PRESET = {
    "main_story": "Mostly internal.",
    "rationale": "Region SEA drove the decline.",
    "causes": {
        "internal": [{"claim": "SEA segment issue", "evidence_ids": ["L1"], "likelihood": "Likely"}],
        "market": [{"claim": "Genre trend was stable", "evidence_ids": ["L1"], "likelihood": "Possible"}],
    },
    "scenarios": [{"description": "Hotfix", "likelihood": "Possible", "evidence_ids": ["L1"], "signals_to_watch": []}],
    "risks": [{"description": "Churn", "likelihood": "Possible", "evidence_ids": []}],
    "assumptions_and_gaps": [],
}

_BENCHMARK_DATES = {
    "2026-05-01": 100.0,
    "2026-05-02": 99.0,
    "2026-05-03": 97.0,
}


def _make_metrics_df():
    rows = []
    for d, sea, na in [("2026-05-01", 1000.0, 800.0), ("2026-05-03", 400.0, 770.0)]:
        rows.append({"date": d, "metric": "dau", "value": sea, "region": "SEA"})
        rows.append({"date": d, "metric": "dau", "value": na, "region": "NA"})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["platform", "version", "cohort", "device", "source"]:
        df[col] = None
    return df


def _deps(tmp_path):
    """Build all dependencies for GraphAgent with pipeline wiring."""
    tmp = str(tmp_path)

    # Profile and metrics stores with an active profile
    ps = ProfileStore(os.path.join(tmp, "p.sqlite"))
    ms = MetricsStore(os.path.join(tmp, "m"))
    prof = GameProfile(
        name="SurvivalGame",
        platform="roblox",
        genre="survival",
        mapping=ColumnMapping(date_col="date", metric_cols={"dau": "dau"}, dim_cols={}),
    )
    ps.save(prof)
    ps.set_active("SurvivalGame")
    ms.save("SurvivalGame", _make_metrics_df())

    # BenchmarkStore pre-seeded so refresher short-circuits as "fresh"
    bstore = BenchmarkStore(os.path.join(tmp, "bench.db"))
    bstore.put_quant("roblox", "survival", raw=_BENCHMARK_DATES)
    benchmark = CrawlingBenchmarkSource(bstore)

    # BenchmarkRefresher — no providers so short-circuits to "fresh"
    refresher = BenchmarkRefresher(bstore, providers_by_platform={}, web_provider=None)

    # Synthesizer with preset LLM response
    llm = FakeLLM(_PRESET)
    synth = Synthesizer(llm)
    signals = FixtureSignalsSource([])

    pipeline = AnalysisPipeline(
        profiles=ps,
        metrics_store=ms,
        benchmark=benchmark,
        refresher=refresher,
        synth=synth,
        signals=signals,
        n_samples=2,
    )

    jobs = JobStore(os.path.join(tmp, "jobs.db"))

    return dict(
        jobs=jobs,
        pipeline=pipeline,
        profile_store=ps,
        metrics_store=ms,
        benchmark=benchmark,
        profiler=Profiler(llm),
    )


def test_analyze_message_returns_job_id(tmp_path):
    """A free-text analyze message returns mode=analyze with a job_id."""
    agent = GraphAgent(**_deps(tmp_path))
    out = agent.handle({"message": "why did dau drop?"}, session_id="s1", user_id="u1")
    assert out["mode"] == "analyze", f"expected analyze, got {out}"
    assert "job_id" in out
    assert "job_status" in out


def test_analyze_poll_until_done(tmp_path):
    """Poll via analyze_status until done, then check result fields."""
    agent = GraphAgent(**_deps(tmp_path))

    # Submit the job
    out = agent.handle({"message": "why did dau drop?"}, session_id="s1", user_id="u1")
    assert out["mode"] == "analyze"
    job_id = out["job_id"]

    # Poll until done (with a safety cap)
    max_polls = 10
    for _ in range(max_polls):
        if out.get("done"):
            break
        out = agent.handle({"action": "analyze_status", "job_id": job_id},
                           session_id="s1", user_id="u1")
    else:
        pytest.fail(f"Job did not complete within {max_polls} polls; last out={out}")

    assert out["done"] is True
    assert out["mode"] == "analyze"
    assert "hypothesis" in out, "done job must have hypothesis"
    assert "markdown_summary" in out, "done job must have markdown_summary"
    assert "<html" in out.get("html", "").lower(), "done job must have html"
    assert "Mostly internal." in out["markdown_summary"]


def test_setup_turn_when_no_profile(tmp_path):
    """With no active profile, any free-text message returns mode=setup."""
    d = _deps(tmp_path)
    # Replace with empty profile store (no active profile)
    d["profile_store"] = ProfileStore(str(tmp_path / "empty.sqlite"))
    agent = GraphAgent(**d)
    out = agent.handle({"message": "hello"}, session_id="s2", user_id="u2")
    assert out["mode"] == "setup"


def test_analyze_status_unknown_job_id(tmp_path):
    """analyze_status with an unknown job_id returns error."""
    agent = GraphAgent(**_deps(tmp_path))
    out = agent.handle({"action": "analyze_status", "job_id": "nonexistent-id"},
                       session_id="s1", user_id="u1")
    assert out["status"] == "error"
    assert "unknown job_id" in out["error"]
