import httpx

from gaa.notion.client import NotionClient


def make_client(handler, token="ntn_test"):
    """A NotionClient whose HTTP layer is an httpx MockTransport routed by `handler`.

    `handler` is a callable (httpx.Request) -> httpx.Response.
    """
    transport = httpx.MockTransport(handler)
    return NotionClient(token, http=httpx.Client(transport=transport))
