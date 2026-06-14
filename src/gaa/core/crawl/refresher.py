"""BenchmarkRefresher — orchestrates a live crawl for one (platform, genre).

Chooses providers for the platform, discovers comparator games, fetches each
one's raw series, aggregates into a genre series, and stores it.  If the
structured (quant) tier yields too little data it falls back to the web
qualitative tier.  An optional wall-clock *deadline* keeps the call bounded
so a gateway-facing pipeline stage can honour its timeout budget.
"""
import time
from typing import Any


class BenchmarkRefresher:
    """Orchestrate a benchmark crawl for a single (platform, genre) pair.

    Parameters
    ----------
    store:
        A ``BenchmarkStore`` instance used to persist and retrieve results.
    providers_by_platform:
        Mapping of platform name → list of quant providers that implement
        ``discover(genre) -> list[str]`` and ``series_for(id) -> dict[str, float]``.
    web_provider:
        Optional qualitative fallback provider exposing
        ``qualitative(genre, platform, start, end) -> dict | None``.
    comparator_cap:
        Maximum number of comparator IDs fetched per provider (default 5).
    ttl_s:
        Time-to-live in seconds for cached quant data (default 6 hours).
    """

    def __init__(
        self,
        store: Any,
        providers_by_platform: dict[str, list],
        web_provider: Any = None,
        comparator_cap: int = 5,
        ttl_s: float = 21600,
    ) -> None:
        self._store = store
        self._providers_by_platform = providers_by_platform
        self._web_provider = web_provider
        self._comparator_cap = comparator_cap
        self._ttl_s = ttl_s

    def refresh(
        self,
        platform: str,
        genre: str,
        start: str | None = None,
        end: str | None = None,
        deadline: float | None = None,
        metric: str | None = None,
    ) -> dict:
        """Run or short-circuit a benchmark crawl for *(platform, genre)*.

        Returns a status dict with keys:
            ``status``      – "fresh" | "ok" | "empty"
            ``tier``        – data tier used, or None
            ``points``      – number of aggregate date-points stored
            ``partial``     – True if the deadline fired before all IDs were fetched
            ``comparators`` – (ok quant only) number of comparators fetched
            ``qual``        – (ok web only) True
        """
        # ── metric benchmark (independent side-store; best-effort) ────────────
        bench_fn = getattr(self._web_provider, "metric_benchmark", None)
        if (metric and bench_fn is not None
                and not self._store.is_fresh(platform, genre, "benchmark", self._ttl_s)):
            try:
                b = bench_fn(metric, genre, platform, start or "", end or "")
            except Exception:
                b = None
            if b:
                self._store.put_benchmark(platform, genre, metric, b)

        # ── cheap short-circuit ───────────────────────────────────────────────
        if self._store.is_fresh(platform, genre, "quant", self._ttl_s):
            return {"status": "fresh", "tier": "cache", "points": 0, "partial": False}

        aggregate: dict[str, float] = {}
        comparators: list[str] = []
        tier: str | None = None
        partial: bool = False

        # ── quant providers ───────────────────────────────────────────────────
        for provider in self._providers_by_platform.get(platform, []):
            try:
                ids = provider.discover(genre)[: self._comparator_cap]
            except Exception:
                # A failing provider is skipped — don't abort the whole refresh.
                continue

            for id_ in ids:
                if deadline is not None and time.monotonic() > deadline:
                    partial = True
                    break
                try:
                    series = provider.series_for(id_)
                except Exception:
                    continue
                for d, v in series.items():
                    aggregate[d] = aggregate.get(d, 0.0) + v
                comparators.append(id_)

            # Stop after the first provider that yields ≥2 distinct dates.
            if len(aggregate) >= 2:
                tier = provider.tier
                break

        # ── store quant if sufficient ─────────────────────────────────────────
        if len(aggregate) >= 2:
            self._store.put_quant(
                platform,
                genre,
                raw=aggregate,
                meta={"tier": tier, "comparators": comparators, "partial": partial},
            )
            return {
                "status": "ok",
                "tier": tier,
                "comparators": len(comparators),
                "points": len(aggregate),
                "partial": partial,
            }

        # ── web qualitative fallback ──────────────────────────────────────────
        if self._web_provider is not None:
            try:
                q = self._web_provider.qualitative(
                    genre, platform, start or "", end or ""
                )
            except Exception:
                q = None
            if q:
                self._store.put_qual(platform, genre, q)
                return {
                    "status": "ok",
                    "tier": "web",
                    "points": 0,
                    "qual": True,
                    "partial": partial,
                }

        return {"status": "empty", "tier": None, "points": 0, "partial": partial}
