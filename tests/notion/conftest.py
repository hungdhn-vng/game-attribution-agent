import httpx

from gaa.notion.client import NotionClient


def make_client(handler, token="ntn_test"):
    """A NotionClient whose HTTP layer is an httpx MockTransport routed by `handler`.

    `handler` is a callable (httpx.Request) -> httpx.Response.
    """
    transport = httpx.MockTransport(handler)
    return NotionClient(token, http=httpx.Client(transport=transport))


def mock_tools(monkeypatch, handler, *, env=None):
    """Point gaa.notion.tools at a MockTransport-backed client and set NOTION_TOKEN.

    `env` extra vars (e.g. NOTION_BUILDS_DS) are set too.
    """
    from gaa.notion import tools
    monkeypatch.setenv("NOTION_TOKEN", "ntn_test")
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(tools, "_client_factory", lambda token: make_client(handler, token))
