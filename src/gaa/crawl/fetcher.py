from typing import Callable, Optional
from gaa.crawl.cache import DiskCache


def _http_get(url: str) -> str:
    import httpx
    r = httpx.get(url, timeout=20, headers={"User-Agent": "gaa-bot/0.1"})
    r.raise_for_status()
    return r.text


class CachedFetcher:
    """Fetch with read-through disk cache. Cache-first: once a URL is cached it is
    replayed without re-fetching — so a slow/blocked network never stalls a demo run."""
    def __init__(self, cache_dir: str, fetch_fn: Optional[Callable[[str], str]] = None) -> None:
        self._cache = DiskCache(cache_dir)
        self._fetch = fetch_fn or _http_get

    def get(self, url: str) -> str:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        body = self._fetch(url)
        self._cache.put(url, body)
        return body
