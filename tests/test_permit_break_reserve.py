"""Adversarial checks for permit reserve and authorize.

These tests pin the attacks from the break-it pass: a per-tool cap of one,
expiry, revoked and expired keys, non-positive call caps, tool-name length,
Unicode tool ids, a missing agent id, a second finalize, finalize after
expiry, and a wallet whose balance is zero. A refused governed call must
still carry a signed denial receipt.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    APIKeyModel,
    IdempotencyRecordModel,
    McpDispatchAttemptModel,
    PermitModel,
    ReceiptModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.permits import PermitError, get_permit_service
from app.services.receipts import ReceiptError, get_receipt_service
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _future() -> str:
    return (utc_now() + timedelta(minutes=30)).isoformat()


async def _spent_and_counts(permit_id: str) -> tuple[Decimal, dict]:
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit_id)
        assert model is not None
        counts = json.loads(model.tool_call_counts_json or "{}")
        return Decimal(str(model.spent_credits)), counts


async def _set_expires_at(permit_id: str, when) -> None:
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit_id)
        assert model is not None
        model.expires_at = when
        session.add(model)
        await session.commit()


async def _set_wallet_balance(wallet_id: str, balance: Decimal) -> None:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        wallet.balance = balance
        session.add(wallet)
        await session.commit()


async def _issue(
    client: AsyncClient,
    provisioned: dict,
    tool: str,
    *,
    idem: str,
    max_credits: int = 50,
    max_calls: int | None = None,
    extra: dict | None = None,
):
    body = {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": [tool],
        "scopes": [f"tool:{tool}:invoke", "billing:charge"],
        "max_credits": max_credits,
        "expires_at": _future(),
    }
    if max_calls is not None:
        body["max_calls_per_tool"] = {tool: max_calls}
    if extra:
        body.update(extra)
    response = await client.post(
        "/v1/permits",
        json=body,
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": idem},
    )
    return response


async def _reserve(permit_id: str, provisioned: dict, tool: str, amount: Decimal):
    return await get_permit_service().authorize_and_reserve(
        permit_id=permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name=tool,
        estimated_credits=amount,
        key_id=provisioned["key_id"],
    )


@pytest.mark.anyio
async def test_concurrent_reserves_keep_one_slot_when_cap_is_one(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    tool = "cap-one-tool"
    issued = await _issue(client, provisioned, tool, idem="cap-one-permit", max_calls=1)
    assert issued.status_code == 201, issued.text
    permit_id = issued.json()["permit_id"]
    price = Decimal("1")

    async def once():
        return await _reserve(permit_id, provisioned, tool, price)

    results = await asyncio.gather(*[once() for _ in range(6)])
    allowed = [item for item in results if item.allowed]
    denied = [item for item in results if not item.allowed]
    assert len(allowed) == 1
    assert {item.reason for item in denied} == {"permit_max_calls_exceeded"}
    spent, counts = await _spent_and_counts(permit_id)
    assert spent == price
    assert counts.get(tool) == 1

    again = await _reserve(permit_id, provisioned, tool, price)
    assert again.allowed is False
    assert again.reason == "permit_max_calls_exceeded"
    spent_after, counts_after = await _spent_and_counts(permit_id)
    assert spent_after == price
    assert counts_after.get(tool) == 1


@pytest.mark.anyio
async def test_expired_permit_does_not_reserve(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool = "expired-tool"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
        idem_key="expired-permit",
    )
    await _set_expires_at(permit["permit_id"], utc_now() - timedelta(seconds=5))
    denied = await _reserve(permit["permit_id"], provisioned, tool, Decimal("1"))
    assert denied.allowed is False
    assert denied.reason == "permit_expired"
    spent, counts = await _spent_and_counts(permit["permit_id"])
    assert spent == Decimal("0")
    assert counts == {}

    verify = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": tool,
            "estimated_credits": "-1",
        },
        headers=provisioned["agent_headers"],
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["valid"] is False
    assert verify.json()["reason"] == "permit_expired"


@pytest.mark.anyio
async def test_revoked_and_expired_keys_cannot_start_a_reserve(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool = "revoked-key-tool"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
        idem_key="revoked-key-permit",
    )
    verify_body = {
        "permit_id": permit["permit_id"],
        "wallet_id": provisioned["agent_wallet_id"],
        "tool": tool,
        "estimated_credits": "1",
    }

    factory = get_session_factory()
    async with factory() as session:
        key = await session.get(APIKeyModel, provisioned["key_id"])
        assert key is not None
        key.expires_at = utc_now() - timedelta(minutes=5)
        session.add(key)
        await session.commit()
    expired = await client.post(
        "/v1/permits/verify",
        json=verify_body,
        headers=provisioned["agent_headers"],
    )
    assert expired.status_code in {401, 403}, expired.text
    spent, _ = await _spent_and_counts(permit["permit_id"])
    assert spent == Decimal("0")

    async with factory() as session:
        key = await session.get(APIKeyModel, provisioned["key_id"])
        assert key is not None
        key.expires_at = utc_now() + timedelta(days=1)
        key.max_uses = 1
        key.use_count = 1
        session.add(key)
        await session.commit()
    exhausted = await client.post(
        "/v1/permits/verify",
        json=verify_body,
        headers=provisioned["agent_headers"],
    )
    assert exhausted.status_code in {401, 403}, exhausted.text

    revoked = await client.delete(
        f"/v1/api-keys/{provisioned['agent_wallet_id']}/{provisioned['key_id']}",
        headers=BOOTSTRAP_HEADERS,
    )
    assert revoked.status_code == 204, revoked.text
    after = await client.post(
        "/v1/permits/verify",
        json=verify_body,
        headers=provisioned["agent_headers"],
    )
    assert after.status_code in {401, 403}, after.text
    spent, counts = await _spent_and_counts(permit["permit_id"])
    assert spent == Decimal("0")
    assert counts == {}


@pytest.mark.anyio
async def test_zero_and_negative_call_caps_cannot_reserve(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    tool = "call-cap-tool"
    for raw, idem in ((0, "cap-zero"), (-1, "cap-negative"), (True, "cap-bool")):
        response = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": provisioned["agent_wallet_id"],
                "subject_wallet_id": provisioned["agent_wallet_id"],
                "subject_key_id": provisioned["key_id"],
                "allowed_tools": [tool],
                "scopes": [f"tool:{tool}:invoke", "billing:charge"],
                "max_credits": 20,
                "max_calls_per_tool": {tool: raw},
                "expires_at": _future(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": idem},
        )
        assert response.status_code == 422, response.text

    issued = await _issue(client, provisioned, tool, idem="cap-inject", max_calls=1)
    assert issued.status_code == 201, issued.text
    permit_id = issued.json()["permit_id"]
    factory = get_session_factory()
    for stored in (0, -1):
        async with factory() as session:
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            model.max_calls_per_tool_json = json.dumps({tool: stored})
            model.tool_call_counts_json = None
            session.add(model)
            await session.commit()
        denied = await _reserve(permit_id, provisioned, tool, Decimal("1"))
        assert denied.allowed is False
        assert denied.reason == "permit_max_calls_exceeded"
        spent, counts = await _spent_and_counts(permit_id)
        assert spent == Decimal("0")
        assert counts == {}


@pytest.mark.anyio
async def test_tool_names_longer_than_the_receipt_column_are_refused(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    long_tool = "t" * 129
    issued = await _issue(client, provisioned, long_tool, idem="long-tool-permit")
    assert issued.status_code == 422, issued.text

    blank = await _issue(client, provisioned, "", idem="blank-tool-permit")
    assert blank.status_code == 422, blank.text

    request = await client.post(
        "/v1/permit-requests",
        json={
            "issuer_wallet_id": provisioned["agent_wallet_id"],
            "subject_wallet_id": provisioned["agent_wallet_id"],
            "allowed_tools": [long_tool],
            "scopes": [f"tool:{long_tool}:invoke", "billing:charge"],
            "max_credits": 5,
            "expires_at": _future(),
            "justification": "needs a tool name the receipt column can store",
        },
        headers=provisioned["agent_headers"],
    )
    assert request.status_code == 422, request.text

    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="short-tool",
        idem_key="short-tool-permit",
    )
    with pytest.raises(ReceiptError) as raised:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool=long_tool,
            request_payload={"value": "request"},
            response_payload={"error": "permit_tool_not_allowed"},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="denied",
            reason_code="permit_tool_not_allowed",
            audit_event_id=None,
        )
    assert raised.value.reason == "receipt_tool_invalid"

    with pytest.raises(ValueError):
        get_service_registry().register_local(
            service_id=long_tool,
            name="Too Long",
            description="Must not become an invocable tool",
            category=ServiceCategory.AGENT_COMMS,
            func=lambda: {"ok": True},
            credits_per_unit=1.0,
        )


@pytest.mark.anyio
async def test_unicode_tool_ids_do_not_share_a_call_slot(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    nfc = "caf\u00e9-tool"
    nfd = "cafe\u0301-tool"
    lookalike = "caf\u0435-tool"
    issued = await _issue(client, provisioned, nfc, idem="unicode-permit", max_calls=1)
    assert issued.status_code == 201, issued.text
    permit_id = issued.json()["permit_id"]
    price = Decimal("1")
    allowed = await _reserve(permit_id, provisioned, nfc, price)
    assert allowed.allowed is True
    for other in (nfd, lookalike):
        denied = await _reserve(permit_id, provisioned, other, price)
        assert denied.allowed is False
        assert denied.reason == "permit_tool_not_allowed"
    spent, counts = await _spent_and_counts(permit_id)
    assert spent == price
    assert counts == {nfc: 1}


@pytest.mark.anyio
async def test_missing_or_blank_agent_id_cannot_mint_a_wallet(client, clean_database):
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Agent Id Sponsor",
            "email": "agent-id@example.com",
            "initial_credits": 1000,
            "require_kyc": False,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert sponsor.status_code == 201, sponsor.text
    sponsor_id = sponsor.json()["wallet_id"]
    base = {
        "sponsor_wallet_id": sponsor_id,
        "budget_credits": 10,
        "daily_limit": 10,
    }
    missing = await client.post(
        "/v1/billing/wallets/agent",
        json=base,
        headers=BOOTSTRAP_HEADERS,
    )
    assert missing.status_code == 422, missing.text
    blank = await client.post(
        "/v1/billing/wallets/agent",
        json={**base, "agent_id": ""},
        headers=BOOTSTRAP_HEADERS,
    )
    assert blank.status_code == 422, blank.text
    spaces = await client.post(
        "/v1/billing/wallets/agent",
        json={**base, "agent_id": "   "},
        headers=BOOTSTRAP_HEADERS,
    )
    assert spaces.status_code == 422, spaces.text
    oversized = await client.post(
        "/v1/billing/wallets/agent",
        json={**base, "agent_id": "a" * 101},
        headers=BOOTSTRAP_HEADERS,
    )
    assert oversized.status_code == 422, oversized.text

    provisioned = await provision_agent_wallet(client)
    issued = await _issue(
        client, provisioned, "agent-optional-tool", idem="agent-optional-permit"
    )
    assert issued.status_code == 201, issued.text


@pytest.mark.anyio
async def test_negative_and_unstorable_amounts_do_not_change_spent(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    tool = "amount-tool"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
        idem_key="amount-permit",
        max_credits=10,
    )
    permit_id = permit["permit_id"]
    service = get_permit_service()

    held = await _reserve(permit_id, provisioned, tool, Decimal("4"))
    assert held.allowed is True
    before, counts_before = await _spent_and_counts(permit_id)
    assert before == Decimal("4")

    for amount in (
        Decimal("-4"),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("0.000000001"),
        Decimal("1.123456789"),
    ):
        denied = await _reserve(permit_id, provisioned, tool, amount)
        assert denied.allowed is False
        assert denied.reason == "permit_amount_invalid"
        with pytest.raises(PermitError) as reserved:
            await service.reserve_budget(permit_id, amount)
        assert reserved.value.reason == "permit_amount_invalid"
        with pytest.raises(PermitError) as released:
            await service.release_budget(permit_id, amount)
        assert released.value.reason == "permit_amount_invalid"
        spent, counts = await _spent_and_counts(permit_id)
        assert spent == before
        assert counts == counts_before

    verify = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit_id,
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": tool,
            "estimated_credits": "-1",
        },
        headers=provisioned["agent_headers"],
    )
    assert verify.status_code == 200, verify.text
    body = verify.json()
    assert body["valid"] is False
    assert body["reason"] == "permit_amount_invalid"
    spent, _ = await _spent_and_counts(permit_id)
    assert spent == before

    # A price the caller left out is zero, and zero still fits the column.
    omitted = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit_id,
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": tool,
        },
        headers=provisioned["agent_headers"],
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["valid"] is True
    explicit_zero = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit_id,
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": tool,
            "estimated_credits": "0",
        },
        headers=provisioned["agent_headers"],
    )
    assert explicit_zero.status_code == 200, explicit_zero.text
    assert explicit_zero.json()["valid"] is True


@pytest.mark.anyio
async def test_zero_balance_blocks_issuance_and_reserve_uses_permit_budget(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    tool = "zero-balance-tool"
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
        idem_key="zero-balance-permit",
        max_credits=10,
    )
    await _set_wallet_balance(provisioned["agent_wallet_id"], Decimal("0"))
    blocked = await _issue(
        client,
        provisioned,
        tool,
        idem="zero-balance-second",
        max_credits=10,
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["detail"] == "permit_budget_exceeds_wallet_balance"

    # Reserve checks the permit budget. The wallet balance is charged later.
    reserved = await _reserve(permit["permit_id"], provisioned, tool, Decimal("2"))
    assert reserved.allowed is True
    spent, _ = await _spent_and_counts(permit["permit_id"])
    assert spent == Decimal("2")
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, provisioned["agent_wallet_id"])
        assert wallet is not None
        assert wallet.balance == Decimal("0")


@pytest.mark.anyio
async def test_second_finalize_and_finalize_after_expiry_keep_accounting(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    tool = "finalize-tool"
    issued = await _issue(
        client, provisioned, tool, idem="finalize-permit", max_calls=1, max_credits=20
    )
    assert issued.status_code == 201, issued.text
    permit_id = issued.json()["permit_id"]
    price = Decimal("3")
    reserved = await _reserve(permit_id, provisioned, tool, price)
    assert reserved.allowed is True

    record_id = "idm_break_finalize_0001"
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            IdempotencyRecordModel(
                record_id=record_id,
                wallet_id=provisioned["agent_wallet_id"],
                endpoint="/mcp/invoke",
                idempotency_key="finalize-once",
                request_hash="ab" * 32,
            )
        )
        await session.commit()

    await _set_expires_at(permit_id, utc_now() - timedelta(seconds=2))
    receipts = get_receipt_service()
    kwargs = dict(
        permit_id=permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool=tool,
        request_payload={"value": "request"},
        response_payload={"value": "done"},
        ledger_entry_id=None,
        credits_authorized=price,
        credits_charged=price,
        outcome="success",
        audit_event_id=None,
        idempotency_record_id=record_id,
    )
    first = await receipts.create_receipt(**kwargs)
    second = await receipts.create_receipt(**kwargs)
    assert second.receipt_id == first.receipt_id
    async with factory() as session:
        stored = await session.scalar(
            select(func.count())
            .select_from(ReceiptModel)
            .where(ReceiptModel.permit_id == permit_id)
        )
    assert stored == 1
    valid, reason, _ = await receipts.verify_receipt(first.receipt_id)
    assert (valid, reason) == (True, None)

    late = await _reserve(permit_id, provisioned, tool, price)
    assert late.allowed is False
    assert late.reason == "permit_expired"
    spent, counts = await _spent_and_counts(permit_id)
    assert spent == price
    assert counts.get(tool) == 1

    attempt_id = "dsp-break-finalize-0001"
    async with factory() as session:
        session.add(
            McpDispatchAttemptModel(
                attempt_id=attempt_id,
                idempotency_record_id=record_id,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit_id,
                key_id=provisioned["key_id"],
                public_tool_id=tool,
                upstream_tool_name="partner_lookup",
                upstream_origin="https://partner.example",
                request_hash="ab" * 32,
                credits_authorized=price,
                state="returned_error",
                call_slot_reserved=True,
            )
        )
        await session.commit()

    released = await get_permit_service().release_dispatch_budget_once(attempt_id)
    assert released is True
    spent, counts = await _spent_and_counts(permit_id)
    assert spent == Decimal("0")
    assert counts.get(tool, 0) == 0
    again = await get_permit_service().release_dispatch_budget_once(attempt_id)
    assert again is False
    spent, counts = await _spent_and_counts(permit_id)
    assert spent == Decimal("0")
    assert counts.get(tool, 0) == 0

    # A slot that was already dispatched stays consumed after the budget returns.
    issued_used = await _issue(
        client,
        provisioned,
        "finalize-used-tool",
        idem="finalize-used-permit",
        max_calls=1,
        max_credits=20,
    )
    assert issued_used.status_code == 201, issued_used.text
    used_id = issued_used.json()["permit_id"]
    used_tool = "finalize-used-tool"
    used = await _reserve(used_id, provisioned, used_tool, price)
    assert used.allowed is True
    used_record = "idm_break_finalize_0002"
    used_attempt = "dsp-break-finalize-0002"
    async with factory() as session:
        session.add(
            IdempotencyRecordModel(
                record_id=used_record,
                wallet_id=provisioned["agent_wallet_id"],
                endpoint="/mcp/invoke",
                idempotency_key="finalize-used",
                request_hash="cd" * 32,
            )
        )
        session.add(
            McpDispatchAttemptModel(
                attempt_id=used_attempt,
                idempotency_record_id=used_record,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=used_id,
                key_id=provisioned["key_id"],
                public_tool_id=used_tool,
                upstream_tool_name="partner_lookup",
                upstream_origin="https://partner.example",
                request_hash="cd" * 32,
                credits_authorized=price,
                state="returned_error",
                call_slot_reserved=True,
                dispatched_at=utc_now(),
            )
        )
        await session.commit()
    released_used = await get_permit_service().release_dispatch_budget_once(
        used_attempt
    )
    assert released_used is True
    spent, counts = await _spent_and_counts(used_id)
    assert spent == Decimal("0")
    assert counts.get(used_tool) == 1


@pytest.mark.anyio
async def test_refused_call_still_has_a_signed_denial_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    allowed = "break-allowed-tool"
    refused = "break-refused-tool"
    for service_id in (allowed, refused):
        registry.register_local(
            service_id=service_id,
            name=service_id,
            description="Break-it denial receipt",
            category=ServiceCategory.AGENT_COMMS,
            func=lambda: {"ok": True},
            credits_per_unit=2.0,
        )
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=allowed,
            idem_key="denial-receipt-permit",
        )
        denied = await client.post(
            f"/mcp/tools/{refused}/invoke",
            json={
                "name": refused,
                "arguments": {},
                "mcp_context": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "denial-receipt-1",
                },
            },
            headers=provisioned["agent_headers"],
        )
        assert denied.status_code == 403, denied.text
        detail = denied.json()["detail"]
        assert detail["error"] == "permit_tool_not_allowed"
        receipt = detail["receipt"]
        assert receipt["outcome"] == "denied"
        assert Decimal(str(receipt["credits_charged"])) == Decimal("0")
        assert receipt["reason_code"] == "permit_tool_not_allowed"
        valid, reason, _ = await get_receipt_service().verify_receipt(
            receipt["receipt_id"]
        )
        assert (valid, reason) == (True, None)
        spent, counts = await _spent_and_counts(permit["permit_id"])
        assert spent == Decimal("0")
        assert counts == {}

        replay = await client.post(
            f"/mcp/tools/{refused}/invoke",
            json={
                "name": refused,
                "arguments": {},
                "mcp_context": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "denial-receipt-1",
                },
            },
            headers=provisioned["agent_headers"],
        )
        assert replay.status_code == 403, replay.text
        assert replay.json()["detail"]["receipt"]["receipt_id"] == receipt["receipt_id"]
        async with get_session_factory()() as session:
            stored = await session.scalar(
                select(func.count())
                .select_from(ReceiptModel)
                .where(ReceiptModel.permit_id == permit["permit_id"])
            )
        assert stored == 1
    finally:
        registry.unregister_local(allowed)
        registry.unregister_local(refused)
