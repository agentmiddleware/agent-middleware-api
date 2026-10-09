"""Retries for the AWI Python SDK client.

``AWIClientConfig`` advertises ``max_retries``, so transient failures
(network errors, 429, 5xx) must be retried and permanent failures
(other 4xx) must be returned without a retry.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _awi_sdk():  # type: ignore[no-untyped-def]
    """Import the unpackaged AWI Python SDK from the checkout."""
    sdk_path = str(REPO_ROOT / "awi_sdk" / "python")
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)
    import awi_sdk

    return awi_sdk


@pytest.fixture
def scripted(monkeypatch):  # type: ignore[no-untyped-def]
    """Build SDK clients whose transport plays one scripted outcome.

    Each outcome is an HTTP status int or an exception instance to
    raise. Every attempt is recorded in ``seen``. The transport is
    injected at client construction (the same pattern as the
    adapter ``wire`` fixture), so proxy settings cannot divert it.
    """
    state: dict[str, Any] = {"outcomes": [], "seen": []}
    real_async_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        seen = state["seen"]
        outcomes = state["outcomes"]

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return httpx.Response(outcome, json={"ok": True})

        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return state


async def test_retries_transient_status_then_succeeds(scripted) -> None:  # type: ignore[no-untyped-def]
    sdk = _awi_sdk()
    scripted["outcomes"].extend([503, 503, 200])
    client = sdk.AWIClient(base_url="http://sdk.test")
    try:
        result = await client.discover()
    finally:
        await client.close()

    assert result == {"ok": True}
    assert len(scripted["seen"]) == 3


async def test_gives_up_after_max_retries(scripted) -> None:  # type: ignore[no-untyped-def]
    sdk = _awi_sdk()
    scripted["outcomes"].extend([503, 503, 503, 503])
    client = sdk.AWIClient(base_url="http://sdk.test", max_retries=2)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.discover()
    finally:
        await client.close()

    # First attempt plus two retries, then the error surfaces.
    assert len(scripted["seen"]) == 3


async def test_does_not_retry_client_errors(scripted) -> None:  # type: ignore[no-untyped-def]
    sdk = _awi_sdk()
    scripted["outcomes"].extend([403])
    client = sdk.AWIClient(base_url="http://sdk.test")
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.discover()
    finally:
        await client.close()

    assert len(scripted["seen"]) == 1


async def test_retries_connect_errors_then_succeeds(scripted) -> None:  # type: ignore[no-untyped-def]
    sdk = _awi_sdk()
    scripted["outcomes"].extend([httpx.ConnectError("connection refused"), 200])
    client = sdk.AWIClient(base_url="http://sdk.test")
    try:
        result = await client.discover()
    finally:
        await client.close()

    assert result == {"ok": True}
    assert len(scripted["seen"]) == 2


async def test_zero_retries_tries_once(scripted) -> None:  # type: ignore[no-untyped-def]
    sdk = _awi_sdk()
    scripted["outcomes"].extend([503])
    client = sdk.AWIClient(base_url="http://sdk.test", max_retries=0)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.discover()
    finally:
        await client.close()

    assert len(scripted["seen"]) == 1


async def test_execute_retry_reuses_idempotency_key(scripted) -> None:  # type: ignore[no-untyped-def]
    sdk = _awi_sdk()
    scripted["outcomes"].extend([503, 200])
    client = sdk.AWIClient(base_url="http://sdk.test")
    try:
        await client.execute(
            "sess-1",
            "add_to_cart",
            {"sku": "laptop-1"},
            permit_id="permit-123",
            idempotency_key="idem-123",
        )
    finally:
        await client.close()

    assert len(scripted["seen"]) == 2
    for request in scripted["seen"]:
        assert request.headers["X-Permit-Id"] == "permit-123"
        assert request.headers["Idempotency-Key"] == "idem-123"
