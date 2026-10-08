"""QA gap-surface tests for b2a_sdk: typed money errors, client error mapping,
governed-loop rejections, post-signature envelope cross-checks, verify_cli
exit codes, edge-client validation, x402 settle mapping, @billable gating.
Two known charge() bugs in in-flight client.py are xfail(strict=True).

Fast and deterministic: httpx.MockTransport only, throwaway signing keys,
no sleeps, no network.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from b2a_sdk import (
    AgentMiddlewareClient,
    AuthorizationError,
    DeliveryUncertainError,
    IdempotencyConflictError,
    InsufficientFundsError,
    PermitDeniedError,
    verify_cli,
)
from b2a_sdk.decorators import billable
from b2a_sdk.edge_client import B2AEdgeClient
from b2a_sdk.errors import APIError
from b2a_sdk.receipt_verifier import (
    CANONICALIZATION,
    VerificationError,
    VerificationResult,
    VerificationStatus,
    canonical_json,
    key_set_from_document,
    verify_bundle,
)
from b2a_sdk.x402 import X402Client


def _sdk_client(handler) -> AgentMiddlewareClient:
    return AgentMiddlewareClient(
        api_key="test-key",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )


# errors.py: typed money errors carry what callers need to recover


class TestMoneyErrors:
    def test_shortfall_string_coerced_to_float(self):
        assert InsufficientFundsError(wallet_id="w-1", shortfall="12.5").shortfall == 12.5
        assert InsufficientFundsError(wallet_id="w-1").shortfall is None

    def test_top_up_url_in_message_only_when_present(self):
        with_url = InsufficientFundsError(wallet_id="w-1", top_up_url="https://x/top-up")
        assert "https://x/top-up" in str(with_url)
        assert with_url.status_code == 402
        without_url = InsufficientFundsError(wallet_id="w-1")
        assert "Top up" not in str(without_url)

    def test_permit_denied_is_authorization_error_with_403(self):
        error = PermitDeniedError("permit_tool_not_allowed", receipt_id="rcpt-1")
        assert isinstance(error, AuthorizationError)
        assert error.status_code == 403
        assert error.reason == "permit_tool_not_allowed"
        assert error.receipt_id == "rcpt-1"

    def test_delivery_uncertain_needs_receipt_id_and_uses_504(self):
        error = DeliveryUncertainError(receipt_id="rcpt-9")
        assert error.receipt_id == "rcpt-9"
        assert error.status_code == 504
        assert APIError("boom").payload == {}


# client.py: HTTP error mapping, malformed bodies, governed-loop rejections


class TestRequestJsonGuards:
    @pytest.mark.asyncio
    async def test_402_maps_shortfall_and_top_up_url(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                402,
                json={"detail": {"shortfall": "7.5", "top_up_url": "https://x/top-up"}},
            )

        async with _sdk_client(handler) as client:
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.discover_tools()
        assert exc_info.value.shortfall == 7.5
        assert exc_info.value.top_up_url == "https://x/top-up"

    @pytest.mark.asyncio
    async def test_non_json_body_is_typed_api_error(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>maintenance</html>")

        async with _sdk_client(handler) as client:
            with pytest.raises(APIError, match="invalid_json_response"):
                await client.discover_tools()

    @pytest.mark.asyncio
    async def test_discover_tools_rejects_malformed_shapes(self):
        for body in (
            {"tools": "not-a-list"},
            {"tools": [{"description": "no name"}]},
            {},
        ):

            async def handler(request: httpx.Request, _b=body) -> httpx.Response:
                return httpx.Response(200, json=_b)

            async with _sdk_client(handler) as client:
                with pytest.raises(APIError, match="invalid_tools_response"):
                    await client.discover_tools()

    def _evidence_receipt(self) -> dict:
        return {
            "receipt_id": "rcpt-1",
            "permit_id": "permit-1",
            "wallet_id": "wallet-1",
            "tool": "partner.search",
            "request_hash": "a" * 64,
            "credits_authorized": "2",
            "credits_charged": "2",
            "outcome": "success",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "signature": "sig",
            "signature_key_id": "key-1",
        }

    @pytest.mark.asyncio
    async def test_get_evidence_rejects_bad_verification_block(self):
        bodies = (
            {"receipt": None},
            {"receipt": self._evidence_receipt(), "verification": "ok", "valid": True},
            {"receipt": self._evidence_receipt(), "verification": {}, "valid": "yes"},
            {"receipt": self._evidence_receipt(), "valid": True},
        )
        for body in bodies:

            async def handler(request: httpx.Request, _b=body) -> httpx.Response:
                return httpx.Response(200, json=_b)

            async with _sdk_client(handler) as client:
                with pytest.raises(APIError):
                    await client.get_evidence("rcpt-1")


class TestInvokeToolGuards:
    def _envelope(self, result=None, error=None) -> dict:
        envelope: dict = {"jsonrpc": "2.0", "id": "k-1"}
        if error is not None:
            envelope["error"] = error
        else:
            envelope["result"] = result
        return envelope

    def _receipt(self, outcome="success") -> dict:
        return {
            "receipt_id": f"rcpt-{outcome}",
            "permit_id": "permit-1",
            "wallet_id": "wallet-1",
            "tool": "partner.search",
            "request_hash": "a" * 64,
            "credits_authorized": "2",
            "credits_charged": "2",
            "outcome": outcome,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "signature": "sig",
            "signature_key_id": "key-1",
        }

    def _invoke(self, envelope: dict):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=envelope)

        return _sdk_client(handler)

    @pytest.mark.asyncio
    async def test_blank_idempotency_key_sends_nothing(self):
        seen: list = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        async with _sdk_client(handler) as client:
            with pytest.raises(ValueError, match="must not be blank"):
                await client.invoke_tool(
                    "t", {}, wallet_id="w", permit_id="p", idempotency_key="  "
                )
        assert seen == []

    @pytest.mark.asyncio
    async def test_delivery_uncertain_result_raises_with_receipt_id(self):
        envelope = self._envelope(
            result={
                "content": [{"type": "text", "text": "x"}],
                "receipt": self._receipt("delivery_uncertain"),
            }
        )
        async with self._invoke(envelope) as client:
            with pytest.raises(DeliveryUncertainError) as exc_info:
                await client.invoke_tool("t", {}, wallet_id="w", permit_id="p", idempotency_key="k")
        assert exc_info.value.receipt_id == "rcpt-delivery_uncertain"

    @pytest.mark.asyncio
    async def test_missing_receipt_is_typed(self):
        envelope = self._envelope(result={"content": [{"type": "text", "text": "x"}]})
        async with self._invoke(envelope) as client:
            with pytest.raises(APIError, match="missing_receipt"):
                await client.invoke_tool("t", {}, wallet_id="w", permit_id="p", idempotency_key="k")

    @pytest.mark.asyncio
    async def test_uncertain_without_receipt_is_never_typed_as_uncertain(self):
        envelope = self._envelope(error={"code": -32603, "message": "delivery_uncertain"})
        async with self._invoke(envelope) as client:
            with pytest.raises(APIError, match="delivery_uncertain_without_receipt"):
                await client.invoke_tool("t", {}, wallet_id="w", permit_id="p", idempotency_key="k")

    @pytest.mark.asyncio
    async def test_permit_reason_in_envelope_is_typed_even_with_code(self):
        envelope = self._envelope(
            error={
                "code": -32003,
                "message": "permit_budget_exceeded",
                "data": {"receipt": self._receipt("denied")},
            }
        )
        async with self._invoke(envelope) as client:
            with pytest.raises(PermitDeniedError) as exc_info:
                await client.invoke_tool("t", {}, wallet_id="w", permit_id="p", idempotency_key="k")
        assert exc_info.value.receipt_id == "rcpt-denied"


# receipt_verifier.py: post-signature envelope cross-checks (signed fixtures)


def _signed_bundle_fixture(extra_payload=None, envelope_overrides=None):
    """A genuinely signed bundle plus its key set (throwaway key)."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    kid = "qa4-test-key"
    payload = {
        "kid": kid,
        "receipt_id": "rcpt-qa4",
        "alg": "Ed25519",
        "canonicalization": CANONICALIZATION,
    }
    payload.update(extra_payload or {})
    signing_input = canonical_json(payload)
    signature = private.sign(signing_input.encode("utf-8"))
    bundle = {
        "receipt_id": "rcpt-qa4",
        "kid": kid,
        "alg": "Ed25519",
        "canonicalization": CANONICALIZATION,
        "signing_input": signing_input,
        "signature": base64.b64encode(signature).decode(),
        "issuer": "https://api.example.com",
    }
    bundle.update(envelope_overrides or {})
    return bundle, {kid: public_raw}


class TestSignedEnvelopeCrossChecks:
    def test_valid_bundle_verifies_with_claims(self):
        bundle, keys = _signed_bundle_fixture()
        result = verify_bundle(bundle, keys)
        assert result.ok
        assert result.receipt_id == "rcpt-qa4"
        assert result.claims["receipt_id"] == "rcpt-qa4"

    def test_tampered_bytes_are_invalid_not_unknown(self):
        bundle, keys = _signed_bundle_fixture()
        bundle["signing_input"] = bundle["signing_input"].replace("rcpt-qa4", "rcpt-qa5")
        result = verify_bundle(bundle, keys)
        assert result.status is VerificationStatus.INVALID
        assert result.is_tampered
        assert result.is_rejected

    def test_relabelled_envelope_kid_is_mismatch(self):
        bundle, keys = _signed_bundle_fixture()
        bundle["kid"] = "some-other-kid"
        result = verify_bundle(bundle, keys)
        assert result.status is VerificationStatus.MISMATCH
        assert result.is_rejected
        assert not result.is_tampered

    def test_relabelled_envelope_receipt_id_is_mismatch(self):
        bundle, keys = _signed_bundle_fixture()
        bundle["receipt_id"] = "rcpt-someone-elses"
        result = verify_bundle(bundle, keys)
        assert result.status is VerificationStatus.MISMATCH
        assert result.is_rejected

    def test_wrong_payload_hash_is_mismatch(self):
        payload = {"kid": "qa4-test-key", "receipt_id": "rcpt-qa4", "payload_hash": "0" * 64}
        bundle, keys = _signed_bundle_fixture(extra_payload=payload)
        assert bundle["signing_input"]  # signed over the stated wrong hash
        result = verify_bundle(bundle, keys)
        assert result.status is VerificationStatus.MISMATCH

    def test_signed_kid_confusion_downgrade_is_mismatch(self):
        """A payload naming an unknown kid but signed by the envelope key."""
        pytest.importorskip("cryptography")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private = Ed25519PrivateKey.generate()
        public_raw = private.public_key().public_bytes_raw()
        payload = {"kid": "unknown-kid", "receipt_id": "rcpt-qa4"}
        signing_input = canonical_json(payload)
        bundle = {
            "receipt_id": "rcpt-qa4",
            "kid": "envelope-kid",
            "signing_input": signing_input,
            "signature": base64.b64encode(private.sign(signing_input.encode())).decode(),
        }
        result = verify_bundle(bundle, {"envelope-kid": public_raw})
        assert result.status is VerificationStatus.MISMATCH

    def test_signed_payload_without_kid_is_malformed(self):
        bundle, keys = _signed_bundle_fixture(extra_payload={"kid": None})
        # kid None is falsy: treated as missing before any key lookup.
        result = verify_bundle(bundle, {"qa4-test-key": keys["qa4-test-key"]})
        assert result.status is VerificationStatus.MALFORMED


class TestKeySetParsing:
    def test_non_dict_document_rejected(self):
        with pytest.raises(VerificationError):
            key_set_from_document(["not", "a", "dict"])

    def test_empty_raw_key_falls_back_to_jwk(self):
        document = {
            "keys": [
                {
                    "kid": "jwk-fallback",
                    "alg": "Ed25519",
                    "public_key_b64": "",
                    "jwk": {"crv": "Ed25519", "x": "D" * 43},
                },
            ]
        }
        assert set(key_set_from_document(document)) == {"jwk-fallback"}


# verify_cli.py: exit codes branch scripts between fraud and outage


class TestVerifyCliExitCodes:
    def _write(self, tmp_path, name, body) -> str:
        path = tmp_path / name
        path.write_text(json.dumps(body), encoding="utf-8")
        return str(path)

    def _keys_doc(self, kid="k-1") -> dict:
        return {"keys": [{"kid": kid, "alg": "Ed25519", "public_key_b64": "A" * 43 + "="}]}

    def test_invalid_signature_is_exit_1(self, tmp_path, capsys):
        pytest.importorskip("cryptography")
        bundle_dict, key_set = _signed_bundle_fixture()
        bundle_dict["signing_input"] = bundle_dict["signing_input"].replace(
            "rcpt-qa4", "rcpt-forged"
        )
        bundle = self._write(tmp_path, "bundle.json", bundle_dict)
        kid, raw = next(iter(key_set.items()))
        keys = self._write(
            tmp_path,
            "keys.json",
            {
                "keys": [
                    {"kid": kid, "alg": "Ed25519", "public_key_b64": base64.b64encode(raw).decode()}
                ]
            },
        )
        assert verify_cli.main(["--bundle", bundle, "--keys", keys]) == 1
        assert "INVALID" in capsys.readouterr().err

    def test_mocked_outcomes_map_to_exit_codes(self, tmp_path, monkeypatch):
        bundle = self._write(tmp_path, "bundle.json", {"receipt_id": "x"})
        keys = self._write(tmp_path, "keys.json", self._keys_doc())
        cases = [
            (VerificationStatus.VERIFIED, 0),
            (VerificationStatus.INVALID, 1),
            (VerificationStatus.MISMATCH, 1),
            (VerificationStatus.UNKNOWN_KEY, 2),
            (VerificationStatus.MALFORMED, 2),
            (VerificationStatus.UNSUPPORTED, 2),
        ]
        for status, expected in cases:
            monkeypatch.setattr(
                verify_cli,
                "verify_bundle",
                lambda b, k, expected_issuer=None, _s=status: VerificationResult(
                    status=_s, reason="r", receipt_id="rcpt-1", key_id="k-1"
                ),
            )
            assert verify_cli.main(["--bundle", bundle, "--keys", keys]) == expected


# edge_client.py: validation fails before any request leaves the process


class TestEdgeClientValidation:
    def test_auth_headers_carry_key_only_when_set(self):
        assert B2AEdgeClient(api_key=None)._auth_headers() == {}
        assert B2AEdgeClient(api_key="edge-key")._auth_headers() == {"X-API-Key": "edge-key"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("permit_id", ["", "   ", None])
    async def test_execute_awi_action_rejects_blank_permit(self, permit_id):
        client = B2AEdgeClient(api_key="k")
        with pytest.raises(ValueError, match="permit_id"):
            await client.execute_awi_action(
                "sess-1", "click", {}, permit_id=permit_id, idempotency_key="k-1"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["", "   ", "k" * 129, None])
    async def test_execute_awi_action_rejects_bad_key(self, key):
        client = B2AEdgeClient(api_key="k")
        with pytest.raises(ValueError, match="[Ii]dempotency"):
            await client.execute_awi_action(
                "sess-1", "click", {}, permit_id="permit-1", idempotency_key=key
            )


# x402.py: header parsing, one-step handling, settle error mapping


def _httpx_like(status_code, headers):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers
    return response


class TestX402ClientBehavior:
    def _x402(self, handler) -> X402Client:
        return X402Client(
            api_key="test-key", base_url="http://test", transport=httpx.MockTransport(handler)
        )

    @pytest.mark.asyncio
    async def test_handle_402_returns_none_for_non_demand(self):
        posts: list = []

        async def handler(request: httpx.Request) -> httpx.Response:
            posts.append(request)
            return httpx.Response(200, json={})

        async with self._x402(handler) as client:
            assert (
                await client.handle_402(
                    _httpx_like(200, {}), permit_id="p", wallet_id="w", idempotency_key="k-1"
                )
                is None
            )
            assert (
                await client.handle_402(
                    _httpx_like(402, {"X-402-Amount": "1"}),
                    permit_id="p",
                    wallet_id="w",
                    idempotency_key="k-1",
                )
                is None
            )
        assert posts == []

    @pytest.mark.asyncio
    async def test_handle_402_settles_a_real_demand(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/x402/settle"
            assert request.headers["idempotency-key"] == "settle-1"
            return httpx.Response(200, json={"receipt_id": "rct-1"})

        async with self._x402(handler) as client:
            result = await client.handle_402(
                _httpx_like(
                    402,
                    {
                        "X-402-Amount": "1.50",
                        "X-402-Payto": "0x1234",
                        "X-402-Network": "base",
                    },
                ),
                permit_id="pmt-1",
                wallet_id="w-1",
                idempotency_key="settle-1",
            )
        assert result == {"receipt_id": "rct-1"}

    @pytest.mark.asyncio
    async def test_settle_permit_denial_is_typed_on_400(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"detail": "permit_budget_exceeded"})

        async with self._x402(handler) as client:
            with pytest.raises(PermitDeniedError):
                await client.settle_402(
                    permit_id="p",
                    wallet_id="w",
                    requirement={"amount_usd": "1", "pay_to": "0x1", "network": "base"},
                    idempotency_key="k-1",
                )

    @pytest.mark.asyncio
    async def test_settle_conflict_is_typed(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"detail": "idempotency_key_reused"})

        async with self._x402(handler) as client:
            with pytest.raises(IdempotencyConflictError):
                await client.settle_402(
                    permit_id="p",
                    wallet_id="w",
                    requirement={"amount_usd": "1", "pay_to": "0x1", "network": "base"},
                    idempotency_key="k-1",
                )


# decorators.py: billing gates and sync misuse


class TestDecoratorGaps:
    @pytest.mark.asyncio
    async def test_billable_sync_function_raises_on_call(self):
        client = MagicMock()

        @billable(client, wallet_id="w", service_category="svc")
        def sync_fn():
            return "never"

        with pytest.raises(RuntimeError, match="@billable requires an async function"):
            await sync_fn()

    @pytest.mark.asyncio
    async def test_billable_denial_skips_function_body(self):
        client = MagicMock()
        client.charge = AsyncMock(side_effect=InsufficientFundsError(wallet_id="w"))
        ran = False

        @billable(client, wallet_id="w", service_category="svc")
        async def guarded():
            nonlocal ran
            ran = True

        with pytest.raises(InsufficientFundsError):
            await guarded()
        assert ran is False


# Known bugs in in-flight client.py stay xfail(strict=True) here;
# product edits there are reserved by another draft PR.


class TestKnownChargeBugs:
    @pytest.mark.xfail(
        strict=True,
        reason="BUG client.py charge(): 402 with a non-JSON body raises "
        "json.JSONDecodeError instead of InsufficientFundsError",
    )
    @pytest.mark.asyncio
    async def test_charge_402_non_json_body_is_typed(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, content=b"<html>maintenance</html>")

        async with _sdk_client(handler) as client:
            with pytest.raises(InsufficientFundsError):
                await client.charge("wallet-123", "iot_bridge", units=10)

    @pytest.mark.xfail(
        strict=True,
        reason="BUG client.py charge(): 402 with a string detail crashes on "
        "str.get instead of raising InsufficientFundsError",
    )
    @pytest.mark.asyncio
    async def test_charge_402_string_detail_is_typed(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"detail": "insufficient_funds"})

        async with _sdk_client(handler) as client:
            with pytest.raises(InsufficientFundsError):
                await client.charge("wallet-123", "iot_bridge", units=10)
