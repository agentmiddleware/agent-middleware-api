"""AWI client retries side-effect-free GETs and never auto-retries writes."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from awi_sdk.client import AWIClient, AWIClientConfig  # noqa: E402


def _client(handler, **config_kwargs):
    """An AWIClient whose transport is fully scripted, counting attempts."""
    seen: list[httpx.Request] = []
    config_kwargs.setdefault("base_url", "http://test")

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request, len(seen))

    client = AWIClient(AWIClientConfig(**config_kwargs))
    client._client = httpx.AsyncClient(
        base_url=config_kwargs["base_url"],
        transport=httpx.MockTransport(wrapped),
    )
    return client, seen


@pytest.mark.asyncio
async def test_get_retries_transient_then_succeeds():
    """Two 503s followed by 200: discover returns, after 3 attempts."""
    client, seen = _client(
        lambda req, n: httpx.Response(
            503 if n < 3 else 200, json={"detail": "busy"} if n < 3 else {"actions": []}
        ),
        max_retries=3,
    )

    result = await client.discover()

    assert result == {"actions": []}
    assert len(seen) == 3


@pytest.mark.asyncio
async def test_get_gives_up_after_max_retries():
    """A persistently sick server surfaces, after exactly 1 + max_retries tries."""
    client, seen = _client(
        lambda req, n: httpx.Response(503, json={"detail": "busy"}),
        max_retries=2,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.discover()

    assert len(seen) == 3


@pytest.mark.asyncio
async def test_max_retries_zero_means_single_attempt():
    client, seen = _client(
        lambda req, n: httpx.Response(503, json={"detail": "busy"}),
        max_retries=0,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_queue_status()

    assert len(seen) == 1


@pytest.mark.asyncio
async def test_client_error_is_not_retried():
    """A 404 is an answer, not a transient failure: one attempt only."""
    client, seen = _client(lambda req, n: httpx.Response(404, json={"detail": "nope"}))

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_session("missing")

    assert len(seen) == 1


def _flaky_then_ok(request: httpx.Request, n: int) -> httpx.Response:
    if n == 1:
        raise httpx.ConnectError("down", request=request)
    return httpx.Response(200, json={"status": "ok"})


@pytest.mark.asyncio
async def test_dropped_connection_is_retried():
    """A connect failure followed by 200 succeeds on the second attempt."""
    client, seen = _client(_flaky_then_ok, max_retries=3)

    result = await client.get_task_status("task-1")

    assert result == {"status": "ok"}
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_execute_never_retries_automatically():
    """A governed POST fails after one attempt; the caller reissues the key."""
    client, seen = _client(
        lambda req, n: httpx.Response(503, json={"detail": "busy"}),
        max_retries=3,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.execute(
            "session-1",
            "search_and_sort",
            {"query": "laptops"},
            permit_id="permit-1",
            idempotency_key="key-1",
        )

    assert len(seen) == 1


@pytest.mark.parametrize("bad", [-1, "3", 2.5, True])
def test_bad_max_retries_rejected(bad):
    """Nonsense retry budgets fail at construction, not mid-request."""
    with pytest.raises(ValueError):
        AWIClientConfig(max_retries=bad)
