"""Adversarial break-it probes for receipts service and receipt routers.

Local tests only. Each test asserts the behavior the contract requires;
a probe that fails on current code names a real break to fix.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import ReceiptModel, SigningKeyModel
from app.main import app
from app.services.receipts import ReceiptError, get_receipt_service
from tests.test_trust_helpers import (
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_receipt(
    client,
    *,
    tool="adv-tool",
    outcome="denied",
    reason_code="adv_probe",
    idem="adv-permit-1",
    request_payload=None,
    response_payload=None,
    constraints=None,
    idempotency_record_id=None,
):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
        idem_key=idem,
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool=tool,
        request_payload=request_payload or {"probe": "one"},
        response_payload=response_payload
        if response_payload is not None
        else {"ok": False},
        ledger_entry_id=None,
        credits_authorized=Decimal("1"),
        credits_charged=Decimal("0"),
        outcome=outcome,
        reason_code=reason_code,
        audit_event_id=None,
        constraints_evaluated=constraints,
        idempotency_record_id=idempotency_record_id,
    )
    return provisioned, permit, receipt


@pytest.mark.anyio
async def test_adv_tamper_reason_code_after_sign_fails_verify(client, clean_database):
    provisioned, _, receipt = await _make_receipt(client)
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(ReceiptModel, receipt.receipt_id)
        assert model is not None
        model.reason_code = "adv_tampered_code"
        session.add(model)
        await session.commit()
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False
    assert reason == "receipt_signature_invalid"


@pytest.mark.anyio
async def test_adv_tamper_credits_after_sign_fails_verify(client, clean_database):
    provisioned, _, receipt = await _make_receipt(client)
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(ReceiptModel, receipt.receipt_id)
        assert model is not None
        model.credits_charged = Decimal("1")
        session.add(model)
        await session.commit()
    valid, _, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False


@pytest.mark.anyio
async def test_adv_swapped_signatures_both_fail_verify(client, clean_database):
    _, _, first = await _make_receipt(client, tool="adv-swap-a", idem="adv-swap-pa")
    _, _, second = await _make_receipt(client, tool="adv-swap-b", idem="adv-swap-pb")
    factory = get_session_factory()
    async with factory() as session:
        a = await session.get(ReceiptModel, first.receipt_id)
        b = await session.get(ReceiptModel, second.receipt_id)
        assert a is not None and b is not None
        a_sig, b_sig = a.signature, b.signature
        a.signature, b.signature = b_sig, a_sig
        # Keep key ids aligned with the swapped signatures so the swap is
        # the only thing under test.
        a_kid, b_kid = a.signature_key_id, b.signature_key_id
        a.signature_key_id, b.signature_key_id = b_kid, a_kid
        session.add(a)
        session.add(b)
        await session.commit()
    svc = get_receipt_service()
    valid_a, _, _ = await svc.verify_receipt(first.receipt_id)
    valid_b, _, _ = await svc.verify_receipt(second.receipt_id)
    assert valid_a is False
    assert valid_b is False


@pytest.mark.anyio
async def test_adv_unknown_key_id_fails_closed_no_500(client, clean_database):
    from sqlalchemy import text

    provisioned, _, receipt = await _make_receipt(client)
    factory = get_session_factory()
    async with factory() as session:
        # Simulate a receipt whose key row is gone (backup restore, manual
        # row delete): FK enforcement would otherwise block this write.
        await session.execute(text("PRAGMA foreign_keys=OFF"))
        model = await session.get(ReceiptModel, receipt.receipt_id)
        assert model is not None
        model.signature_key_id = "kid-that-was-never-issued"
        session.add(model)
        await session.commit()
        await session.execute(text("PRAGMA foreign_keys=ON"))
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False
    assert reason == "receipt_signature_invalid"
    assert await get_receipt_service().signing_input(receipt.receipt_id) is None
    resp = await client.get(
        f"/v1/receipts/{receipt.receipt_id}/portable",
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "receipt_signature_invalid"
    verify = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt.receipt_id},
        headers=provisioned["agent_headers"],
    )
    assert verify.status_code == 200
    assert verify.json()["valid"] is False


@pytest.mark.anyio
async def test_adv_corrupt_signature_bytes_fail_closed_no_500(client, clean_database):
    provisioned, _, receipt = await _make_receipt(client)
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(ReceiptModel, receipt.receipt_id)
        assert model is not None
        model.signature = "!!!not-valid-base64!!!"
        session.add(model)
        await session.commit()
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False
    assert reason == "receipt_signature_invalid"
    verify = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt.receipt_id},
        headers=provisioned["agent_headers"],
    )
    assert verify.status_code == 200
    assert verify.json()["valid"] is False


@pytest.mark.anyio
async def test_adv_wrong_length_signature_fails_closed(client, clean_database):
    import base64

    _, _, receipt = await _make_receipt(client)
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(ReceiptModel, receipt.receipt_id)
        assert model is not None
        model.signature = base64.b64encode(b"too-short").decode()
        session.add(model)
        await session.commit()
    valid, _, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False


@pytest.mark.anyio
async def test_adv_corrupt_stored_pubkey_fails_closed_no_500(client, clean_database):
    _, _, receipt = await _make_receipt(client)
    factory = get_session_factory()
    async with factory() as session:
        key = await session.get(SigningKeyModel, receipt.signature_key_id)
        assert key is not None
        key.public_key_b64 = "!!!corrupt!!!"
        session.add(key)
        await session.commit()
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False
    assert reason == "receipt_signature_invalid"


@pytest.mark.anyio
async def test_adv_disabled_key_fails_closed_retired_still_verifies(
    client, clean_database
):
    from app.services.signing_keys import get_signing_key_service

    _, _, receipt = await _make_receipt(client)
    keys = get_signing_key_service()
    factory = get_session_factory()

    async with factory() as session:
        key = await session.get(SigningKeyModel, receipt.signature_key_id)
        assert key is not None
        key.status = "retired"
        from app.core.time import utc_now

        key.retired_at = utc_now()
        session.add(key)
        await session.commit()
    valid, _, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is True

    async with factory() as session:
        key = await session.get(SigningKeyModel, receipt.signature_key_id)
        assert key is not None
        key.status = "disabled"
        session.add(key)
        await session.commit()
    valid, reason, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is False
    assert reason == "receipt_signature_invalid"
    assert keys is get_signing_key_service()


@pytest.mark.anyio
async def test_adv_empty_payloads_create_and_verify(client, clean_database):
    provisioned, _, receipt = await _make_receipt(
        client,
        request_payload={},
        response_payload={},
        tool="adv-empty",
        idem="adv-empty-permit",
    )
    valid, _, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is True


@pytest.mark.anyio
async def test_adv_unicode_tool_and_arguments_verify(client, clean_database):
    provisioned, _, receipt = await _make_receipt(
        client,
        tool="adv-outil-cafe",
        request_payload={"message": "caf\u00e9 \u2615 \u65e5\u672c\u8a9e \U0001f600"},
        response_payload={"echo": "\u00e9\u00e8\u00ea \u6f22\u5b57"},
        idem="adv-unicode-permit",
    )
    valid, _, _ = await get_receipt_service().verify_receipt(receipt.receipt_id)
    assert valid is True
    fetched = await get_receipt_service().get_receipt(receipt.receipt_id)
    assert fetched is not None
    assert fetched.tool == "adv-outil-cafe"


@pytest.mark.anyio
async def test_adv_unicode_reason_code_rejected(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-ureason",
        idem_key="adv-ureason-permit",
    )
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="adv-ureason",
            request_payload={"a": 1},
            response_payload={"b": 2},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="denied",
            reason_code="refus\u00e9_caf\u00e9",
            audit_event_id=None,
        )
    assert exc.value.reason == "receipt_reason_code_invalid"


@pytest.mark.anyio
async def test_adv_unknown_outcome_rejected(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-outcome",
        idem_key="adv-outcome-permit",
    )
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="adv-outcome",
            request_payload={"a": 1},
            response_payload={"b": 2},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="banana",
            reason_code="adv_probe",
            audit_event_id=None,
        )
    assert exc.value.reason == "receipt_outcome_invalid"


@pytest.mark.anyio
async def test_adv_idempotency_reuse_with_different_tool_conflicts(
    client, clean_database
):
    from app.services.idempotency import get_idempotency_service

    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-idem",
        idem_key="adv-idem-permit",
    )
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/mcp/messages",
        idempotency_key="adv-idem-invoke-1",
        request_payload={"n": 1},
    )
    assert begun.replay is None
    kwargs = dict(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="adv-idem",
        request_payload={"n": 1},
        response_payload={"ok": False},
        ledger_entry_id=None,
        credits_authorized=Decimal("1"),
        credits_charged=Decimal("0"),
        outcome="denied",
        reason_code="adv_probe",
        audit_event_id=None,
        idempotency_record_id=begun.record_id,
    )
    first = await get_receipt_service().create_receipt(**kwargs)
    replayed = await get_receipt_service().create_receipt(**kwargs)
    assert replayed.receipt_id == first.receipt_id
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            **{**kwargs, "tool": "adv-other-tool"}
        )
    assert exc.value.reason == "receipt_idempotency_conflict"


@pytest.mark.anyio
async def test_adv_idempotency_reuse_with_different_constraints_conflicts(
    client, clean_database
):
    from app.services.idempotency import get_idempotency_service

    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-idemc",
        idem_key="adv-idemc-permit",
    )
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/mcp/messages",
        idempotency_key="adv-idemc-invoke-1",
        request_payload={"n": 1},
    )
    assert begun.replay is None
    kwargs = dict(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="adv-idemc",
        request_payload={"n": 1},
        response_payload={"ok": False},
        ledger_entry_id=None,
        credits_authorized=Decimal("1"),
        credits_charged=Decimal("0"),
        outcome="denied",
        reason_code="adv_probe",
        audit_event_id=None,
        idempotency_record_id=begun.record_id,
        constraints_evaluated={"scope": "first"},
    )
    first = await get_receipt_service().create_receipt(**kwargs)
    assert first.constraints_evaluated == {"scope": "first"}
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            **{**kwargs, "constraints_evaluated": {"scope": "second"}}
        )
    assert exc.value.reason == "receipt_idempotency_conflict"


@pytest.mark.anyio
async def test_adv_denied_receipt_shape_and_verify(client, clean_database):
    provisioned, _, denied = await _make_receipt(
        client,
        outcome="denied",
        reason_code="adv_denied",
        tool="adv-shape-d",
        idem="adv-shape-pd",
    )
    assert denied.ledger_entry_id is None
    assert denied.credits_charged == Decimal("0")
    assert denied.outcome == "denied"
    assert denied.reason_code == "adv_denied"
    assert denied.signature
    assert denied.signature_key_id
    valid, _, _ = await get_receipt_service().verify_receipt(denied.receipt_id)
    assert valid is True

    _, _, success = await _make_receipt(
        client,
        outcome="success",
        reason_code=None,
        tool="adv-shape-s",
        idem="adv-shape-ps",
    )
    assert success.reason_code is None
    valid, _, _ = await get_receipt_service().verify_receipt(success.receipt_id)
    assert valid is True


@pytest.mark.anyio
async def test_adv_success_with_reason_code_rejected(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-sreason",
        idem_key="adv-sreason-permit",
    )
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="adv-sreason",
            request_payload={"a": 1},
            response_payload={"b": 2},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("1"),
            outcome="success",
            reason_code="adv_probe",
            audit_event_id=None,
        )
    assert exc.value.reason == "receipt_reason_code_invalid"


@pytest.mark.anyio
async def test_adv_request_identity_edges(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-reqid",
        idem_key="adv-reqid-permit",
    )
    base = dict(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="adv-reqid",
        response_payload={"b": 2},
        ledger_entry_id=None,
        credits_authorized=Decimal("1"),
        credits_charged=Decimal("0"),
        outcome="denied",
        reason_code="adv_probe",
        audit_event_id=None,
    )
    # Both payload and hash.
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            **base,
            request_payload={"a": 1},
            request_hash="ab" * 32,
        )
    assert exc.value.reason == "receipt_request_identity_invalid"
    # Neither payload nor hash.
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            **base,
            request_payload=None,
            request_hash=None,
        )
    assert exc.value.reason == "receipt_request_identity_invalid"
    # Non-hex hash.
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            **base,
            request_payload=None,
            request_hash="zz" * 32,
        )
    assert exc.value.reason == "receipt_request_hash_invalid"
    # Short hash.
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            **base,
            request_payload=None,
            request_hash="ab",
        )
    assert exc.value.reason == "receipt_request_hash_invalid"
    # Uppercase hex normalizes and verifies.
    upper = await get_receipt_service().create_receipt(
        **base,
        request_payload=None,
        request_hash="AB" * 32,
    )
    assert upper.request_hash == "ab" * 32
    valid, _, _ = await get_receipt_service().verify_receipt(upper.receipt_id)
    assert valid is True


@pytest.mark.anyio
async def test_adv_response_hash_override_mismatch_rejected(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-rhash",
        idem_key="adv-rhash-permit",
    )
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="adv-rhash",
            request_payload={"a": 1},
            response_payload={"b": 2},
            response_hash_override="00" * 32,
            dispatch_attempt_id="adv-attempt-1",
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="denied",
            reason_code="adv_probe",
            audit_event_id=None,
        )
    assert exc.value.reason == "receipt_response_hash_mismatch"
    # Override without a dispatch attempt id is also refused.
    from app.services.signing_keys import sha256_hex, canonical_json

    correct = sha256_hex(canonical_json({"b": 2}, ensure_ascii=False, allow_nan=False))
    with pytest.raises(ReceiptError) as exc2:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="adv-rhash",
            request_payload={"a": 1},
            response_payload={"b": 2},
            response_hash_override=correct,
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="denied",
            reason_code="adv_probe",
            audit_event_id=None,
        )
    assert exc2.value.reason == "receipt_response_hash_override_invalid"


@pytest.mark.anyio
async def test_adv_cross_wallet_receipt_read_denied(client, clean_database):
    first = await provision_agent_wallet(client)
    second = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=first["agent_wallet_id"],
        key_id=first["key_id"],
        tool_name="adv-xwallet",
        idem_key="adv-xwallet-permit",
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=first["agent_wallet_id"],
        key_id=first["key_id"],
        tool="adv-xwallet",
        request_payload={"a": 1},
        response_payload={"b": 2},
        ledger_entry_id=None,
        credits_authorized=Decimal("1"),
        credits_charged=Decimal("0"),
        outcome="denied",
        reason_code="adv_probe",
        audit_event_id=None,
    )
    cross = await client.get(
        f"/v1/receipts/{receipt.receipt_id}",
        headers=second["agent_headers"],
    )
    assert cross.status_code == 403
    own = await client.get(
        f"/v1/receipts/{receipt.receipt_id}",
        headers=first["agent_headers"],
    )
    assert own.status_code == 200
    anon = await client.get(f"/v1/receipts/{receipt.receipt_id}")
    assert anon.status_code in (401, 403)


@pytest.mark.anyio
async def test_adv_receipt_list_requires_scope(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    anon = await client.get("/v1/receipts")
    assert anon.status_code in (401, 403)
    scoped = await client.get(
        "/v1/receipts",
        params={"wallet_id": provisioned["agent_wallet_id"]},
        headers=provisioned["agent_headers"],
    )
    assert scoped.status_code == 200


@pytest.mark.anyio
async def test_adv_negative_credits_rejected(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="adv-neg",
        idem_key="adv-neg-permit",
    )
    with pytest.raises(ReceiptError) as exc:
        await get_receipt_service().create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="adv-neg",
            request_payload={"a": 1},
            response_payload={"b": 2},
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("-1"),
            outcome="denied",
            reason_code="adv_probe",
            audit_event_id=None,
        )
    assert exc.value.reason == "receipt_credits_invalid"
