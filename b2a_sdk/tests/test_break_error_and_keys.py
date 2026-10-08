"""Adversarial checks for charge 402 mapping, x402 permit status, and key headers.

These tests use httpx.MockTransport only. Nothing here talks to a live server.
"""

import httpx
import pytest

from b2a_sdk import (
    AgentMiddlewareClient,
    APIError,
    AuthorizationError,
    IdempotencyConflictError,
    InsufficientFundsError,
    PermitDeniedError,
    X402Client,
)
from b2a_sdk.edge_client import B2AEdgeClient


def _recording_client(response: httpx.Response):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    client = AgentMiddlewareClient(
        api_key="test-key",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    return client, seen


def _x402_client(response: httpx.Response):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    client = X402Client(
        api_key="test-key",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    return client, seen


async def _edge_client(response: httpx.Response):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    client = B2AEdgeClient(api_url="http://test", api_key="test-key", wallet_id="wallet-123")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, seen


_SETTLE_KW = {
    "permit_id": "pmt-123",
    "wallet_id": "wallet-123",
    "requirement": {
        "amount_usd": "10.50",
        "pay_to": "0x1234",
        "network": "ethereum",
    },
    "idempotency_key": "settle-001",
}


class TestCharge402Mapping:
    """charge() must raise InsufficientFundsError for every HTTP 402 body."""

    @pytest.mark.asyncio
    async def test_string_detail_is_insufficient_funds_not_attribute_error(self):
        client, seen = _recording_client(httpx.Response(402, json={"detail": "insufficient_funds"}))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge", idempotency_key="charge-1")

        err = exc_info.value
        assert err.status_code == 402
        assert err.wallet_id == "wallet-123"
        assert err.shortfall is None
        assert err.payload == {"detail": "insufficient_funds"}
        assert seen[0].headers["idempotency-key"] == "charge-1"
        assert seen[0].headers["x-api-key"] == "test-key"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "detail",
        [
            {"shortfall": None, "error": "insufficient_funds"},
            {"shortfall": "nope", "error": "insufficient_funds"},
            {"shortfall": True, "error": "insufficient_funds"},
            ["insufficient_funds"],
        ],
    )
    async def test_bad_shortfall_does_not_hide_the_402(self, detail):
        body = {"detail": detail}
        client, _ = _recording_client(httpx.Response(402, json=body))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge")

        assert exc_info.value.shortfall is None
        assert exc_info.value.status_code == 402
        assert exc_info.value.payload == body

    @pytest.mark.asyncio
    async def test_non_json_402_still_raises_insufficient_funds(self):
        client, _ = _recording_client(httpx.Response(402, content=b"not-json"))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge")

        assert exc_info.value.shortfall is None
        assert exc_info.value.payload == {}
        assert exc_info.value.wallet_id == "wallet-123"

    @pytest.mark.asyncio
    async def test_server_top_up_url_is_kept(self):
        body = {
            "detail": {
                "error": "insufficient_funds",
                "shortfall": "2.5",
                "top_up_url": "/v1/billing/top-up/prepare",
                "wallet_id": "wallet-123",
            }
        }
        client, _ = _recording_client(httpx.Response(402, json=body))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge", units=3)

        err = exc_info.value
        assert err.shortfall == 2.5
        assert err.top_up_url == "http://test/v1/billing/top-up/prepare"
        assert err.payload == body

    @pytest.mark.asyncio
    async def test_absolute_top_up_url_is_not_rewritten(self):
        body = {
            "detail": {
                "shortfall": 4,
                "top_up_url": "https://pay.example/top-up",
            }
        }
        client, _ = _recording_client(httpx.Response(402, json=body))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge")

        assert exc_info.value.top_up_url == "https://pay.example/top-up"
        assert exc_info.value.shortfall == 4.0

    @pytest.mark.asyncio
    async def test_missing_top_up_url_keeps_dashboard_fallback(self):
        client, _ = _recording_client(httpx.Response(402, json={"detail": {"shortfall": "100.0"}}))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge")

        assert exc_info.value.shortfall == 100.0
        assert exc_info.value.top_up_url == "http://test/dashboard/top-up?wallet=wallet-123"

    @pytest.mark.asyncio
    async def test_403_is_still_an_http_error(self):
        """wallet_frozen and wallet_access_denied stay HTTP 403, not a 402."""
        client, _ = _recording_client(
            httpx.Response(
                403,
                json={
                    "detail": {
                        "error": "wallet_frozen",
                        "wallet_id": "wallet-123",
                        "shortfall": "1.0",
                    }
                },
            )
        )
        async with client:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.charge("wallet-123", "iot_bridge", idempotency_key="charge-1")

        assert exc_info.value.response.status_code == 403

    @pytest.mark.asyncio
    async def test_shared_http_402_bad_shortfall_stays_typed(self):
        """Routes that share _raise_http_error must not crash on a bad shortfall."""
        client, _ = _recording_client(
            httpx.Response(
                402, json={"detail": {"shortfall": "nope", "error": "insufficient_funds"}}
            )
        )
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.discover_tools()

        assert exc_info.value.shortfall is None
        assert exc_info.value.status_code == 402
        assert exc_info.value.payload["detail"]["shortfall"] == "nope"


class TestX402PermitStatus:
    """settle_402 must not relabel a retryable permit failure as a 403 denial."""

    @pytest.mark.asyncio
    async def test_permit_write_contended_stays_503(self):
        body = {"detail": "permit_write_contended"}
        client, seen = _x402_client(httpx.Response(503, json=body))
        async with client:
            with pytest.raises(APIError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        err = exc_info.value
        assert type(err) is APIError
        assert not isinstance(err, PermitDeniedError)
        assert err.status_code == 503
        assert err.detail == "permit_write_contended"
        assert err.payload == body
        assert seen[0].headers["idempotency-key"] == "settle-001"
        assert seen[0].headers["x-api-key"] == "test-key"

    @pytest.mark.asyncio
    async def test_permit_denial_keeps_real_400_status(self):
        body = {"detail": "permit_tool_not_allowed"}
        client, _ = _x402_client(httpx.Response(400, json=body))
        async with client:
            with pytest.raises(PermitDeniedError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        assert exc_info.value.status_code == 400
        assert exc_info.value.reason == "permit_tool_not_allowed"
        assert exc_info.value.payload == body

    @pytest.mark.asyncio
    async def test_permit_not_found_keeps_404(self):
        client, _ = _x402_client(httpx.Response(404, json={"detail": "permit_not_found"}))
        async with client:
            with pytest.raises(PermitDeniedError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        assert exc_info.value.status_code == 404
        assert exc_info.value.reason == "permit_not_found"

    @pytest.mark.asyncio
    async def test_generic_402_stays_api_error(self):
        client, _ = _x402_client(httpx.Response(402, json={"detail": "x402_invalid_requirement"}))
        async with client:
            with pytest.raises(APIError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        assert type(exc_info.value) is APIError
        assert not isinstance(exc_info.value, InsufficientFundsError)
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_body_insufficient_funds_is_typed(self):
        body = {
            "detail": {
                "error": "insufficient_funds",
                "shortfall": "9.5",
                "top_up_url": "/v1/billing/top-up/prepare",
            }
        }
        client, _ = _x402_client(httpx.Response(402, json=body))
        async with client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        err = exc_info.value
        assert err.wallet_id == "wallet-123"
        assert err.shortfall == 9.5
        assert err.top_up_url == "/v1/billing/top-up/prepare"
        assert err.payload == body
        assert err.status_code == 402

    @pytest.mark.asyncio
    async def test_non_permit_403_stays_authorization_error(self):
        client, _ = _x402_client(httpx.Response(403, json={"detail": "wallet_access_denied"}))
        async with client:
            with pytest.raises(AuthorizationError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        assert type(exc_info.value) is AuthorizationError
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_conflict_stays_409(self):
        client, _ = _x402_client(httpx.Response(409, json={"detail": "idempotency_key_reused"}))
        async with client:
            with pytest.raises(IdempotencyConflictError) as exc_info:
                await client.settle_402(**_SETTLE_KW)

        assert exc_info.value.status_code == 409


class TestIdempotencyKeyHeader:
    """A key with a control character must not be sent as a header."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_key", ["job\n1", "job\r1", "job\x001", "job\x7f1"])
    async def test_sdk_charge_rejects_control_characters_before_send(self, bad_key):
        client, seen = _recording_client(httpx.Response(200, json={"ok": True}))
        async with client:
            with pytest.raises(ValueError, match="control characters"):
                await client.charge("wallet-123", "iot_bridge", idempotency_key=bad_key)
        assert seen == []

    @pytest.mark.asyncio
    async def test_sdk_charge_strips_then_accepts_128(self):
        key = " " + ("k" * 128)
        client, seen = _recording_client(httpx.Response(200, json={"ok": True}))
        async with client:
            await client.charge("wallet-123", "iot_bridge", idempotency_key=key)
        assert seen[0].headers["idempotency-key"] == "k" * 128

    @pytest.mark.asyncio
    async def test_edge_execute_rejects_control_characters_and_strips(self):
        client, seen = await _edge_client(httpx.Response(200, json={"ok": True}))
        async with client:
            with pytest.raises(ValueError, match="control characters"):
                await client.execute_awi_action(
                    "sess-1",
                    "click",
                    {},
                    permit_id="permit-1",
                    idempotency_key="act\nion",
                )
            assert seen == []
            await client.execute_awi_action(
                "sess-1",
                "click",
                {},
                permit_id="  permit-1  ",
                idempotency_key="  " + ("a" * 128),
            )
            with pytest.raises(ValueError, match="control characters"):
                await client.execute_awi_action(
                    "sess-1",
                    "click",
                    {},
                    permit_id="perm\nit",
                    idempotency_key="action-1",
                )
        assert seen[0].headers["idempotency-key"] == "a" * 128
        assert seen[0].headers["x-permit-id"] == "permit-1"
        assert seen[0].headers["x-api-key"] == "test-key"
        assert len(seen) == 1
