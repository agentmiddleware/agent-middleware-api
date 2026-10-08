"""Framework client must send the same idempotency key the SDK would send.

httpx.MockTransport only. The legacy client must stay importable without b2a_sdk.
"""

import httpx
import pytest
from framework_integrations.client import B2AClient, B2AConfig


async def _client():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "balance": 10})

    client = B2AClient(B2AConfig(api_url="http://test", api_key="test-key", wallet_id="w-1"))
    original = client._client
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await original.aclose()
    return client, seen


class TestFrameworkIdempotencyKey:
    @pytest.mark.asyncio
    async def test_charge_strips_key_and_keeps_api_key(self):
        client, seen = await _client()
        async with _Closer(client):
            await client.charge("iot_bridge", units=2, idempotency_key="  job-1  ")
            await client.charge("iot_bridge", units=2, idempotency_key="  job-1  ")

        assert len(seen) == 2
        assert seen[0].headers["idempotency-key"] == "job-1"
        assert seen[1].headers["idempotency-key"] == "job-1"
        assert seen[0].headers["x-api-key"] == "test-key"
        assert seen[0].headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_charge_accepts_128_after_strip_and_rejects_129(self):
        client, seen = await _client()
        async with _Closer(client):
            await client.charge("iot_bridge", idempotency_key=" " + ("k" * 128))
            with pytest.raises(ValueError, match="at most 128"):
                await client.charge("iot_bridge", idempotency_key="k" * 129)
            with pytest.raises(ValueError, match="must not be blank"):
                await client.charge("iot_bridge", idempotency_key="   ")

        assert len(seen) == 1
        assert seen[0].headers["idempotency-key"] == "k" * 128

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_key", ["job\n1", "job\r1", "job\x7f1"])
    async def test_charge_rejects_control_characters_before_send(self, bad_key):
        client, seen = await _client()
        async with _Closer(client):
            with pytest.raises(ValueError, match="control characters"):
                await client.charge("iot_bridge", idempotency_key=bad_key)
        assert seen == []

    @pytest.mark.asyncio
    async def test_execute_strips_key_and_permit_and_keeps_headers(self):
        client, seen = await _client()
        async with _Closer(client):
            await client.execute_awi_action(
                "sess-1",
                "click",
                {"x": 1},
                permit_id="  permit-1  ",
                idempotency_key="  " + ("a" * 128),
            )
            with pytest.raises(ValueError, match="control characters"):
                await client.execute_awi_action(
                    "sess-1",
                    "click",
                    {},
                    permit_id="permit-1",
                    idempotency_key="act\nion",
                )
            with pytest.raises(ValueError, match="control characters"):
                await client.execute_awi_action(
                    "sess-1",
                    "click",
                    {},
                    permit_id="perm\nit",
                    idempotency_key="action-1",
                )

        assert len(seen) == 1
        request = seen[0]
        assert request.headers["idempotency-key"] == "a" * 128
        assert request.headers["x-permit-id"] == "permit-1"
        assert request.headers["x-api-key"] == "test-key"
        assert request.url.path == "/v1/awi/execute"


class _Closer:
    """Close whichever client object the test swapped in."""

    def __init__(self, client: B2AClient) -> None:
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *args):
        await self._client.close()
