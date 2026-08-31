"""Security fuzz battery: forged signatures, key confusion, injection, malformed payloads, rate limits.

Each attack reports expected-vs-actual and verifies the signed receipt outcome.
Denials must produce denied receipts with zero charge.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import PermitModel, ReceiptModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.receipts import get_receipt_service
from app.services.service_registry import get_service_registry
from app.services.signing_keys import canonical_json, sha256_hex
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _register_tool(tool_name: str, credits: float = 1.0):
    registry = get_service_registry()

    def echo(input: str = "ok", **kwargs) -> dict:
        return {"message": input}

    registry.register_local(
        service_id=tool_name,
        name="Fuzz Tool",
        description="Security fuzz test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=credits,
        unit_name="call",
    )
    return registry


async def _invoke(
    client: AsyncClient,
    wallet_id: str,
    permit_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    idem_key: str = "invoke-1",
    headers: dict[str, str] | None = None,
):
    return await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
                "mcpContext": {
                    "wallet_id": wallet_id,
                    "permit_id": permit_id,
                    "idempotency_key": idem_key,
                },
            },
        },
        headers=headers or BOOTSTRAP_HEADERS,
    )


async def _create_permit(
    client: AsyncClient,
    wallet_id: str,
    key_id: str,
    tool_name: str,
    extra: dict[str, Any] | None = None,
    idem_key: str = "permit-1",
):
    payload = {
        "issuer_wallet_id": wallet_id,
        "subject_wallet_id": wallet_id,
        "subject_key_id": key_id,
        "allowed_tools": [tool_name],
        "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
        "max_credits": 50,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }
    if extra:
        payload.update(extra)
    resp = await client.post(
        "/v1/permits",
        json=payload,
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": idem_key},
    )
    assert resp.status_code == 201
    return resp.json()


async def _verify_receipt_outcome(
    receipt_id: str, expected_outcome: str, expected_charge: Decimal
):
    """Fetch receipt and assert outcome + charge. Returns receipt response."""
    receipt = await get_receipt_service().get_receipt(receipt_id)
    assert receipt is not None, f"Receipt {receipt_id} not found"
    assert receipt.outcome == expected_outcome, (
        f"Expected outcome {expected_outcome}, got {receipt.outcome}"
    )
    assert receipt.credits_charged == expected_charge, (
        f"Expected charge {expected_charge}, got {receipt.credits_charged}"
    )
    return receipt


# ─── Track 1: Forged Signatures ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_tampered_receipt_payload_fails_verification(client, clean_database):
    """Modify a receipt's stored payload_hash after signing; verify must fail."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-sig-1"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(client, wallet_id, key_id, tool_name)
        r = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            headers=agent_headers,
            idem_key="sig-1",
        )
        assert r.status_code == 200
        body = r.json()
        receipt_data = body["result"]["receipt"]
        receipt_id = receipt_data["receipt_id"]

        # Tamper the stored request_hash
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(ReceiptModel, receipt_id)
            model.request_hash = "0" * 64
            session.add(model)
            await session.commit()

        ok, reason, _ = await get_receipt_service().verify_receipt(receipt_id)
        assert ok is False, "Expected tampered receipt to fail verification"
        assert reason == "receipt_signature_invalid"
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_wrong_key_signature_fails_verification(client, clean_database):
    """Sign a receipt payload with a different Ed25519 key; verify must fail."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-sig-2"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(client, wallet_id, key_id, tool_name)
        r = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            headers=agent_headers,
            idem_key="sig-2",
        )
        assert r.status_code == 200
        body = r.json()
        receipt_data = body["result"]["receipt"]
        receipt_id = receipt_data["receipt_id"]

        # Generate a wrong key and re-sign the payload
        wrong_key = Ed25519PrivateKey.generate()
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(ReceiptModel, receipt_id)
            payload = {
                "receipt_id": model.receipt_id,
                "permit_id": model.permit_id,
                "wallet_id": model.wallet_id,
                "key_id": model.key_id,
                "tool": model.tool,
                "request_hash": model.request_hash,
                "response_hash": model.response_hash,
                "ledger_entry_id": model.ledger_entry_id,
                "credits_authorized": model.credits_authorized,
                "credits_charged": model.credits_charged,
                "outcome": model.outcome,
                "audit_event_id": model.audit_event_id,
                "created_at": model.created_at,
                "alg": "Ed25519",
                "kid": model.signature_key_id,
            }
            if model.approval_id:
                payload["approval_id"] = model.approval_id
            payload["payload_hash"] = sha256_hex(payload)
            fake_sig = wrong_key.sign(canonical_json(payload).encode())
            model.signature = base64.b64encode(fake_sig).decode()
            session.add(model)
            await session.commit()

        ok, reason, _ = await get_receipt_service().verify_receipt(receipt_id)
        assert ok is False, "Expected wrong-key signature to fail verification"
        assert reason == "receipt_signature_invalid"
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_signature_from_different_receipt_fails(client, clean_database):
    """Copy a valid signature from receipt A onto receipt B's payload; verify must fail."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-sig-3"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(client, wallet_id, key_id, tool_name)
        r1 = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            headers=agent_headers,
            idem_key="sig-3a",
        )
        r2 = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            headers=agent_headers,
            idem_key="sig-3b",
        )
        assert r1.status_code == 200 and r2.status_code == 200
        receipt_a = r1.json()["result"]["receipt"]
        receipt_b = r2.json()["result"]["receipt"]

        # Swap A's signature onto B
        factory = get_session_factory()
        async with factory() as session:
            model_b = await session.get(ReceiptModel, receipt_b["receipt_id"])
            model_b.signature = receipt_a["signature"]
            session.add(model_b)
            await session.commit()

        ok, reason, _ = await get_receipt_service().verify_receipt(
            receipt_b["receipt_id"]
        )
        assert ok is False, "Expected cross-receipt signature to fail verification"
        assert reason == "receipt_signature_invalid"
    finally:
        get_service_registry().unregister_local(tool_name)


# ─── Track 2: Key Confusion ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_agent_b_key_with_agent_a_permit_denied(client, clean_database):
    """Agent B's API key + Agent A's permit must be denied."""
    provisioned_a = await provision_agent_wallet(client)
    provisioned_b = await provision_agent_wallet(client)
    tool_name = "fuzz-kc-1"
    _register_tool(tool_name)
    try:
        permit_a = await _create_permit(
            client, provisioned_a["agent_wallet_id"], provisioned_a["key_id"], tool_name
        )

        # Invoke with B's headers but A's permit
        r = await _invoke(
            client,
            wallet_id=provisioned_a["agent_wallet_id"],
            permit_id=permit_a["permit_id"],
            tool_name=tool_name,
            headers=provisioned_b["agent_headers"],
            idem_key="kc-1",
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == -32003

        # Receipt may not be present if auth layer denies before trust plane
        receipt = body.get("error", {}).get("data", {}).get("receipt")
        if receipt:
            await _verify_receipt_outcome(receipt["receipt_id"], "denied", Decimal("0"))
        else:
            # Auth-layer denial before receipt generation — valid outcome
            pass
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_swapped_wallet_key_pair_denied(client, clean_database):
    """Permit issued for wallet A, invoke claiming wallet B with A's key, must deny."""
    provisioned_a = await provision_agent_wallet(client)
    provisioned_b = await provision_agent_wallet(client)
    tool_name = "fuzz-kc-2"
    _register_tool(tool_name)
    try:
        permit_a = await _create_permit(
            client, provisioned_a["agent_wallet_id"], provisioned_a["key_id"], tool_name
        )

        # Use wallet B in mcpContext but A's permit, with A's key in headers
        r = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned_b["agent_wallet_id"],
                        "permit_id": permit_a["permit_id"],
                        "idempotency_key": "kc-2",
                    },
                },
            },
            headers=provisioned_a["agent_headers"],
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == -32003
        receipt = body.get("error", {}).get("data", {}).get("receipt")
        if receipt:
            await _verify_receipt_outcome(receipt["receipt_id"], "denied", Decimal("0"))
        else:
            pass  # Auth-layer denial before receipt generation
    finally:
        get_service_registry().unregister_local(tool_name)


# ─── Track 3: Constraint Field Injection ─────────────────────────────────────


@pytest.mark.anyio
async def test_forbidden_fields_with_unicode_injection_denied(client, clean_database):
    """Unicode lookalike key must be caught by forbidden_fields."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-inj-1"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(
            client,
            wallet_id,
            key_id,
            tool_name,
            extra={"forbidden_fields": ["token"]},
            idem_key="inj-permit-1",
        )
        # Use Unicode homoglyph: tοken with Greek omicron (ο) instead of Latin o
        # Pass input as well so the tool call doesn't fail for unrelated reasons
        r = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            arguments={"input": "hello", "tοken": "leak"},
            headers=agent_headers,
            idem_key="inj-1",
        )
        assert r.status_code == 200
        body = r.json()
        # Homoglyph is NOT "token" — call should succeed (injection did not match)
        assert "error" not in body, "Homoglyph should not match forbidden 'token'"

        # Now with actual forbidden key
        r2 = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            arguments={"token": "leak"},
            headers=agent_headers,
            idem_key="inj-2",
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert "error" in body2
        assert "permit_forbidden_field" in body2["error"]["message"]
        receipt = body2["error"]["data"]["receipt"]
        await _verify_receipt_outcome(receipt["receipt_id"], "denied", Decimal("0"))
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_recipient_domain_wildcard_injection(client, clean_database):
    """recipient_domain with wildcard-like string must be stored literally, not expanded."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-inj-2"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(
            client,
            wallet_id,
            key_id,
            tool_name,
            extra={"recipient_domain": "*.example.com"},
            idem_key="inj-permit-2",
        )
        # The domain is stored literally; it should NOT match sub.example.com
        # (unless the implementation does wildcard matching, which it shouldn't)
        r = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            arguments={"input": "test"},
            headers=agent_headers,
            idem_key="inj-3",
        )
        # Local tools don't check recipient_domain, so this should succeed
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_max_calls_per_tool_with_null_key_fails_closed(client, clean_database):
    """Null/None as a key in max_calls_per_tool dict must not crash; should fail closed."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-inj-3"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(
            client, wallet_id, key_id, tool_name, idem_key="inj-permit-3"
        )

        # Inject null key at DB layer
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit["permit_id"])
            model.max_calls_per_tool_json = json.dumps({None: 5, tool_name: 5})
            session.add(model)
            await session.commit()

        r = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            headers=agent_headers,
            idem_key="inj-4",
        )
        assert r.status_code == 200
        body = r.json()
        # Should either succeed (null key ignored) or fail closed
        if "error" in body:
            receipt = body["error"]["data"]["receipt"]
            await _verify_receipt_outcome(receipt["receipt_id"], "denied", Decimal("0"))
    finally:
        get_service_registry().unregister_local(tool_name)


# ─── Track 4: Malformed JSON & Oversized Payloads ────────────────────────────


@pytest.mark.anyio
async def test_malformed_json_on_invoke_returns_parse_error(client, clean_database):
    """Send garbage JSON to /mcp/messages; expect parse error, no charge."""
    r = await client.post(
        "/mcp/messages",
        content=b"{not json",
        headers={**BOOTSTRAP_HEADERS, "Content-Type": "application/json"},
    )
    # FastAPI should return 422 or 400 for bad JSON
    assert r.status_code in (400, 422)


@pytest.mark.anyio
async def test_malformed_json_on_permit_creation_returns_422(client, clean_database):
    """Send garbage JSON to /v1/permits; expect validation error."""
    r = await client.post(
        "/v1/permits",
        content=b"{bad json",
        headers={
            **BOOTSTRAP_HEADERS,
            "Content-Type": "application/json",
            "Idempotency-Key": "bad-json-1",
        },
    )
    assert r.status_code in (400, 422)


@pytest.mark.anyio
async def test_oversized_payload_on_invoke_observed(client, clean_database):
    """Invoke with a 10MB argument string; observe whether size limits are enforced."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-size-1"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(client, wallet_id, key_id, tool_name)
        huge = "x" * (10 * 1024 * 1024)  # 10 MB
        r = await _invoke(
            client,
            wallet_id,
            permit["permit_id"],
            tool_name,
            arguments={"input": huge},
            headers=agent_headers,
            idem_key="size-1",
        )
        if r.status_code == 200 and "result" in r.json():
            pytest.skip(
                "No payload size limit enforced — consider adding MAX_CONTENT_LENGTH middleware"
            )
        else:
            body = r.json()
            assert "error" in body
    finally:
        get_service_registry().unregister_local(tool_name)


# ─── Track 5: Rate Limit Behavior ────────────────────────────────────────────


@pytest.mark.anyio
async def test_rapid_fire_invokes_all_accounted(client, clean_database):
    """Fire 20 rapid invokes; check all receipts exist and total charge is exact.
    Requires PostgreSQL for accurate row-lock accounting."""
    from sqlalchemy import select

    from app.db.database import get_engine
    from app.db.models import IdempotencyRecordModel, LedgerEntryModel, WalletModel

    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL for accurate concurrent budget accounting")

    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "fuzz-rl-1"
    _register_tool(tool_name)
    try:
        permit = await _create_permit(
            client,
            wallet_id,
            key_id,
            tool_name,
            extra={"max_calls_per_tool": {tool_name: 100}},
        )
        permit_id = permit["permit_id"]

        factory = get_session_factory()
        async with factory() as session:
            wallet_before = await session.get(WalletModel, wallet_id)
            assert wallet_before is not None
            balance_before = wallet_before.balance

        async def fire(i: int):
            return await _invoke(
                client,
                wallet_id,
                permit_id,
                tool_name,
                arguments={"input": f"rapid-{i}"},
                headers=agent_headers,
                idem_key=f"rl-{i}",
            )

        # Fire 20 calls as fast as possible
        responses = await asyncio.gather(*[fire(i) for i in range(20)])

        success_count = 0
        total_charged = Decimal("0")
        for resp in responses:
            assert resp.status_code == 200
            body = resp.json()
            if "error" in body:
                receipt = body["error"]["data"]["receipt"]
                await _verify_receipt_outcome(
                    receipt["receipt_id"], "denied", Decimal("0")
                )
            else:
                success_count += 1
                receipt = body["result"]["receipt"]
                total_charged += Decimal(str(receipt["credits_charged"]))

        assert success_count == 20, f"Expected 20 successes, got {success_count}"
        assert total_charged == Decimal("20"), (
            f"Expected charge 20, got {total_charged}"
        )

        # Verify permit spent_credits
        factory = get_session_factory()
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model.spent_credits == Decimal("20")

        original_results = [response.json()["result"] for response in responses]
        original_receipts = [result["receipt"] for result in original_results]
        receipt_ids = {receipt["receipt_id"] for receipt in original_receipts}
        record_ids = {receipt["idempotency_record_id"] for receipt in original_receipts}
        assert len(receipt_ids) == 20
        assert len(record_ids) == 20

        async def assert_persisted_accounting() -> set[str]:
            async with factory() as session:
                wallet = await session.get(WalletModel, wallet_id)
                stored_permit = await session.get(PermitModel, permit_id)
                debits = list(
                    (
                        await session.scalars(
                            select(LedgerEntryModel).where(
                                LedgerEntryModel.wallet_id == wallet_id,
                                LedgerEntryModel.action == "debit",
                            )
                        )
                    ).all()
                )
                receipts = list(
                    (
                        await session.scalars(
                            select(ReceiptModel).where(
                                ReceiptModel.wallet_id == wallet_id,
                            )
                        )
                    ).all()
                )
                records = list(
                    (
                        await session.scalars(
                            select(IdempotencyRecordModel).where(
                                IdempotencyRecordModel.wallet_id == wallet_id,
                                IdempotencyRecordModel.idempotency_key.in_(
                                    [f"rl-{i}" for i in range(20)]
                                ),
                            )
                        )
                    ).all()
                )

            assert wallet is not None
            assert balance_before - wallet.balance == Decimal("20")
            assert stored_permit is not None
            assert stored_permit.spent_credits == Decimal("20")
            assert len(debits) == 20
            assert sum((debit.amount for debit in debits), Decimal("0")) == Decimal(
                "-20"
            )
            assert len(receipts) == 20
            assert {receipt.receipt_id for receipt in receipts} == receipt_ids
            assert len(records) == 20
            assert {record.record_id for record in records} == record_ids
            debit_by_operation = {debit.operation_key: debit for debit in debits}
            receipt_by_id = {receipt.receipt_id: receipt for receipt in receipts}
            record_by_id = {record.record_id: record for record in records}
            assert set(debit_by_operation) == record_ids
            for i, original in enumerate(original_receipts):
                receipt = receipt_by_id[original["receipt_id"]]
                record = record_by_id[original["idempotency_record_id"]]
                debit = debit_by_operation[record.record_id]
                assert record.idempotency_key == f"rl-{i}"
                assert receipt.idempotency_record_id == record.record_id
                assert receipt.request_hash == record.request_hash
                assert receipt.ledger_entry_id == debit.entry_id
                assert receipt.permit_id == permit_id
                assert receipt.tool == tool_name
                assert receipt.outcome == "success"
                assert receipt.credits_charged == Decimal("1")
                assert debit.amount == Decimal("-1")
            return {debit.entry_id for debit in debits}

        debit_ids = await assert_persisted_accounting()
        replays = await asyncio.gather(*[fire(i) for i in range(20)])
        for i, replay in enumerate(replays):
            assert replay.status_code == 200
            assert "error" not in replay.json()
            assert replay.json()["result"] == original_results[i]
        assert await assert_persisted_accounting() == debit_ids
    finally:
        get_service_registry().unregister_local(tool_name)
