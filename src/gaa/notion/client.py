"""Thin httpx wrapper over the Notion REST API (data-source model, v2025-09-03). Read-only.

Knows HTTP + Notion; nothing about MCP or tool shaping. All failures raise
NotionError carrying http_status (and retry_after for 429) so the tools layer
can map them to structured results.
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://api.notion.com/v1"
_VERSION = "2025-09-03"


class NotionError(Exception):
    def __init__(self, message: str, *, http_status: int | None = None,
                 retry_after: float | None = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after


class NotionClient:
    def __init__(self, token: str, *, http: httpx.Client | None = None, timeout: float = 30.0):
        self._token = token
        self._http = http or httpx.Client(timeout=timeout)

    def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": _VERSION,
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(method, f"{_BASE_URL}{path}", headers=headers, json=json)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            raise NotionError("notion rate limited", http_status=429,
                              retry_after=float(ra) if ra else None)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("message") or body.get("code") or resp.text
            except Exception:
                msg = resp.text
            raise NotionError(msg, http_status=resp.status_code)
        return resp.json()

    def search(self, query: str, *, type: str | None = None, limit: int = 10) -> list[dict]:
        body: dict = {"query": query or "", "page_size": min(int(limit or 10), 100)}
        if type in ("page", "data_source"):
            body["filter"] = {"value": type, "property": "object"}
        return self._request("POST", "/search", json=body).get("results", [])

    def get_data_source(self, ds_id: str) -> dict:
        return self._request("GET", f"/data_sources/{ds_id}")

    def query_data_source(self, ds_id: str, *, sorts: list | None = None,
                          page_size: int = 10) -> list[dict]:
        body: dict = {"page_size": min(int(page_size or 10), 100)}
        if sorts:
            body["sorts"] = sorts
        return self._request("POST", f"/data_sources/{ds_id}/query", json=body).get("results", [])

    def get_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{page_id}")

    def get_block_children(self, block_id: str, *, page_size: int = 50) -> list[dict]:
        # Deliberate single-page read (no has_more/next_cursor follow): callers truncate
        # the extracted text to a token budget anyway, so the first page is enough.
        ps = min(int(page_size or 50), 100)
        return self._request("GET", f"/blocks/{block_id}/children?page_size={ps}").get("results", [])
