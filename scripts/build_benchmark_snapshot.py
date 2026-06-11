"""Build (or refresh) src/gaa/data/seed/benchmark_snapshot.json.

This script is meant to be run by a developer or CI pipeline against the *live*
Roblox and Steam tracker endpoints configured via environment variables.  It is
NEVER executed inside the container or during pytest.

Usage
-----
    . .venv/bin/activate
    export GAA_ROBLOX_DISCOVER_URL_TMPL="https://example.com/roblox/discover?genre={genre}"
    export GAA_ROBLOX_SERIES_URL_TMPL="https://example.com/roblox/series?id={id}"
    export GAA_STEAM_DISCOVER_URL_TMPL="https://example.com/steam/discover?genre={genre}"
    export GAA_STEAM_SERIES_URL_TMPL="https://example.com/steam/series?appid={id}"
    # Optional Perplexity qualitative tier:
    export PERPLEXITY_API_KEY=pplx-...
    python scripts/build_benchmark_snapshot.py

The script will crawl each (platform, genre) pair listed in TARGETS, store the
results in a temporary BenchmarkStore, then dump a snapshot JSON to
src/gaa/data/seed/benchmark_snapshot.json for bundling in the Docker image.
"""
import json
import os
import sys
import tempfile

# Make sure the src package is importable when run from the project root.
_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from gaa.config import Settings
from gaa.crawl.fetcher import CachedFetcher
from gaa.crawl.perplexity import perplexity_answer
from gaa.crawl.refresher import BenchmarkRefresher
from gaa.sources.providers.roblox import RobloxBenchmarkProvider
from gaa.sources.providers.steam import SteamBenchmarkProvider
from gaa.sources.providers.web import WebSearchBenchmarkProvider
from gaa.store.benchmark_store import BenchmarkStore

# ── Configuration ──────────────────────────────────────────────────────────────

TARGETS: list[tuple[str, str]] = [
    ("roblox", "survival"),
    ("roblox", "simulator"),
    ("roblox", "obby"),
    ("roblox", "roleplay"),
    ("steam", "action"),
    ("steam", "rpg"),
    ("steam", "strategy"),
]

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "gaa", "data", "seed", "benchmark_snapshot.json"
)

# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    settings = Settings()

    roblox_discover = os.environ.get("GAA_ROBLOX_DISCOVER_URL_TMPL", "")
    roblox_series = os.environ.get("GAA_ROBLOX_SERIES_URL_TMPL", "")
    steam_discover = os.environ.get("GAA_STEAM_DISCOVER_URL_TMPL", "")
    steam_series = os.environ.get("GAA_STEAM_SERIES_URL_TMPL", "")

    missing = [
        name for name, val in [
            ("GAA_ROBLOX_DISCOVER_URL_TMPL", roblox_discover),
            ("GAA_ROBLOX_SERIES_URL_TMPL", roblox_series),
            ("GAA_STEAM_DISCOVER_URL_TMPL", steam_discover),
            ("GAA_STEAM_SERIES_URL_TMPL", steam_series),
        ] if not val
    ]
    if missing:
        print(f"ERROR: required env vars not set: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        store = BenchmarkStore(os.path.join(tmpdir, "bench.db"))
        fetcher_roblox = CachedFetcher(os.path.join(tmpdir, "cache_roblox"))
        fetcher_steam = CachedFetcher(os.path.join(tmpdir, "cache_steam"))

        roblox_provider = RobloxBenchmarkProvider(
            fetcher=fetcher_roblox,
            discover_url_tmpl=roblox_discover,
            series_url_tmpl=roblox_series,
        )
        steam_provider = SteamBenchmarkProvider(
            fetcher=fetcher_steam,
            discover_url_tmpl=steam_discover,
            series_url_tmpl=steam_series,
        )
        providers_by_platform = {
            "roblox": [roblox_provider],
            "steam": [steam_provider],
        }

        web_provider = None
        if settings.perplexity_api_key:
            print("Perplexity key found — enabling web qualitative tier.")
            web_provider = WebSearchBenchmarkProvider(
                lambda prompt: perplexity_answer(prompt, settings)
            )

        refresher = BenchmarkRefresher(
            store=store,
            providers_by_platform=providers_by_platform,
            web_provider=web_provider,
            ttl_s=0,  # force re-fetch (build tool, not runtime)
        )

        snapshot: dict = {}
        for platform, genre in TARGETS:
            print(f"  Crawling {platform}/{genre} …", end=" ", flush=True)
            info = refresher.refresh(platform, genre)
            print(info.get("status"), f"({info.get('points', 0)} pts)")
            quant = store.get_quant(platform, genre)
            if quant and quant.get("raw"):
                snapshot[f"{platform}/{genre}"] = {
                    "raw": quant["raw"],
                    "tier": quant.get("tier", "snapshot"),
                }
            else:
                print(f"    WARNING: no quant data for {platform}/{genre} — skipping.")

    output_path = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"\nWrote {len(snapshot)} entries → {output_path}")


if __name__ == "__main__":
    main()
