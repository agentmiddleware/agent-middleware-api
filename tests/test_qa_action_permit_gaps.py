"""Deep QA gaps for action permits, permit helpers and receipt reads.

Covers untested behavior in app/services/action_permits.py (binding hash
inputs, strict JSON profile edges, issuance authority, execution identity
scope edges, admission gates) plus small untested helpers in
app/services/permits.py and app/services/receipts.py.

These tests change no product code. Pure validation tests need no database;
the receipt tests reuse the existing wallet and permit fixtures.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.auth import AuthContext
from app.core.time import utc_now
from app.services.action_permits import (
    action_payload_hash,
    canonical_action_payload,
    create_action_permit,
    upstream_action_binding_hash,
    validate_action_request,
)
from app.services.permits import PermitCreationRejectedError
from tests.test_action_permits import BINDING, _action_request
from tests.test_permit_signing_input_snapshot import _base_model

DEFAULT_ARGS = {"amount_minor": 1, "recipient": "alice"}


def _action_model(**overrides):
    """Action permit row whose digest matches DEFAULT_ARGS for subject."""
    subject = overrides.get("subject_wallet_id", "agt-action-subject")
    model = _base_model(
        permit_id="pmt-action-qa-1",
        subject_wallet_id=subject,
        subject_key_id="key-action-1",
        scopes_json=json.dumps(["tool:partner.pay:invoke", "billing:charge"]),
        allowed_tools_json='["partner.pay"]',
        max_calls_per_tool_json='{"partner.pay": 1}',
        expires_at=utc_now() + timedelta(hours=1),
        action_contract_version=1,
        action_payload_hash=action_payload_hash(BINDING, subject, DEFAULT_ARGS),
        action_schema_id=BINDING.schema_id,
        action_schema_version=BINDING.schema_version,
        action_public_tool_id=BINDING.public_tool_id,
        action_upstream_binding_hash=BINDING.upstream_binding_hash,
    )
    return model.model_copy(update=overrides) if overrides else model


def _mock_signature(monkeypatch, ok: bool) -> None:
    from app.services.permits import get_permit_service

    monkeypatch.setattr(
        get_permit_service(), "verify_signature", AsyncMock(return_value=ok)
    )


def _mock_registry(monkeypatch, record, binding):
    from app.services.service_registry import get_service_registry

    registry = get_service_registry()
    monkeypatch.setattr(registry, "get", AsyncMock(return_value=record))
    monkeypatch.setattr(registry, "get_action_binding", lambda _record: binding)


def _bootstrap_auth() -> AuthContext:
    return AuthContext("test", "", is_bootstrap_admin=True)


# Binding hash inputs.


@pytest.mark.parametrize("field", ["deployment_authority", "public_tool_id"])
def test_upstream_binding_hash_rejects_empty_or_non_string(field):
    base = dict(
        deployment_authority="test-plane",
        public_tool_id="partner.pay",
        upstream_origin="https://fixture.invalid",
        upstream_tool_name="pay",
        schema_id="money",
        schema_version="1",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}},
        },
    )
    with pytest.raises(ValueError, match="invalid_action_binding"):
        upstream_action_binding_hash(**{**base, field: ""})
    with pytest.raises(ValueError, match="invalid_action_binding"):
        upstream_action_binding_hash(**{**base, field: None})


def test_upstream_binding_hash_rejects_untyped_schema():
    with pytest.raises(ValueError, match="unsupported_action_schema"):
        upstream_action_binding_hash(
            deployment_authority="test-plane",
            public_tool_id="partner.pay",
            upstream_origin="https://fixture.invalid",
            upstream_tool_name="pay",
            schema_id="money",
            schema_version="1",
            input_schema={"oneOf": []},
        )


def test_upstream_binding_hash_is_stable_and_origin_sensitive():
    kwargs = dict(
        deployment_authority="test-plane",
        public_tool_id="partner.pay",
        upstream_tool_name="pay",
        schema_id="money",
        schema_version="1",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}},
        },
    )
    first = upstream_action_binding_hash(
        upstream_origin="https://fixture.invalid", **kwargs
    )
    assert first == upstream_action_binding_hash(
        upstream_origin="https://fixture.invalid", **kwargs
    )
    assert first != upstream_action_binding_hash(
        upstream_origin="https://other.invalid", **kwargs
    )


# Strict JSON and schema profile edges.


@pytest.mark.parametrize(
    "arguments",
    [
        {"amount_minor": 1, "recipient": ("alice",)},
        {"amount_minor": 1, "recipient": "alice", "extra": float("nan")},
        {1: "bad", "amount_minor": 1, "recipient": "alice"},
    ],
)
def test_strict_json_rejects_tuples_nan_and_non_string_keys(arguments):
    with pytest.raises(ValueError, match="action_arguments_must_be_strict_json"):
        action_payload_hash(BINDING, "wallet", arguments)


def _schema_with(prop: dict) -> dict:
    return {
        "type": "object",
        "properties": {"value": prop},
        "required": ["value"],
    }


@pytest.mark.parametrize(
    "prop",
    [
        {"type": "array", "items": {"type": "integer"}, "minItems": True},
        {"type": "integer", "minimum": "1"},
        {"type": "array", "items": {"type": "integer"}, "additionalProperties": False},
        {"type": "string", "enum": []},
        {"type": "string", "maxLength": -1},
    ],
)
def test_schema_profile_rejects_bool_bounds_empty_enum_and_negative(prop):
    binding = replace(BINDING, input_schema=_schema_with(prop))
    with pytest.raises(ValueError, match="invalid_action_schema|unsupported"):
        action_payload_hash(binding, "wallet", {"value": 1})


def test_validate_rejects_const_mismatch_and_missing_required():
    const_binding = replace(
        BINDING,
        input_schema={
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "const": "alice"},
            },
            "required": ["recipient"],
        },
    )
    with pytest.raises(ValueError, match="action_argument_const"):
        action_payload_hash(const_binding, "wallet", {"recipient": "bob"})
    with pytest.raises(ValueError, match="action_argument_required"):
        action_payload_hash(BINDING, "wallet", {})
    with pytest.raises(ValueError, match="action_argument_type_mismatch"):
        action_payload_hash(
            BINDING, "wallet", {"amount_minor": "1", "recipient": "alice"}
        )


def test_number_type_rejects_bool_while_accepting_int_and_float():
    binding = replace(BINDING, input_schema=_schema_with({"type": "number"}))
    action_payload_hash(binding, "wallet", {"value": 1})
    action_payload_hash(binding, "wallet", {"value": 1.5})
    with pytest.raises(ValueError, match="action_argument_type_mismatch"):
        action_payload_hash(binding, "wallet", {"value": True})


# Canonical payload edges.


def test_canonical_payload_rejects_non_object_args_and_empty_wallet():
    with pytest.raises(ValueError, match="action_arguments_must_be_object"):
        canonical_action_payload(
            BINDING,
            "wallet",
            ["not-a-dict"],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="invalid_action_binding"):
        canonical_action_payload(BINDING, "", dict(DEFAULT_ARGS))
    string_schema = replace(BINDING, input_schema={"type": "string"})
    with pytest.raises(ValueError, match="action_arguments_must_be_object"):
        canonical_action_payload(string_schema, "wallet", dict(DEFAULT_ARGS))


# Issuer authority.


@pytest.mark.anyio
async def test_bootstrap_admin_may_self_issue_action():
    from app.services.action_permits import authorize_action_issuer

    result = await authorize_action_issuer(
        _action_request(issuer_wallet_id="agent", subject_wallet_id="agent"),
        _bootstrap_auth(),
    )
    assert result is None


@pytest.mark.anyio
async def test_wallet_without_issuer_access_is_denied():
    from app.services.action_permits import authorize_action_issuer

    with pytest.raises(HTTPException) as denied:
        await authorize_action_issuer(
            _action_request(),
            AuthContext("test", "", wallet_id="foreign"),
        )
    assert denied.value.status_code == 403


@pytest.mark.anyio
async def test_create_action_permit_requires_registered_binding(monkeypatch):
    _mock_registry(monkeypatch, None, None)
    with pytest.raises(
        PermitCreationRejectedError, match="action_tool_binding_required"
    ):
        await create_action_permit(_action_request(), _bootstrap_auth())


@pytest.mark.anyio
async def test_create_action_permit_requires_binding_on_record(monkeypatch):
    _mock_registry(monkeypatch, {"legacy": True}, None)
    with pytest.raises(
        PermitCreationRejectedError, match="action_tool_binding_required"
    ):
        await create_action_permit(_action_request(), _bootstrap_auth())


@pytest.mark.anyio
async def test_create_action_permit_rejects_invalid_arguments(monkeypatch):
    _mock_registry(monkeypatch, {"fixture": True}, BINDING)
    request = _action_request(arguments={"amount_minor": "1", "recipient": "alice"})
    with pytest.raises(
        PermitCreationRejectedError, match="action_argument_type_mismatch"
    ):
        await create_action_permit(request, _bootstrap_auth())


# Execution identity scope edges.


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_tools_json": "[["},
        {"max_calls_per_tool_json": '{"partner.pay": 1.0}'},
        {"max_calls_per_tool_json": '{"partner.pay": true}'},
        {"action_payload_hash": "A" * 64},
        {"action_contract_version": None},
    ],
)
def test_execution_identity_rejects_malformed_scope_and_digest(changes):
    from app.services.action_permits import action_execution_identity

    with pytest.raises(ValueError):
        action_execution_identity(_action_model(**changes), BINDING)


def test_execution_identity_binds_exact_single_use_scope():
    from app.services.action_permits import action_execution_identity

    identity = action_execution_identity(_action_model(), BINDING)
    assert identity.idempotency_key.startswith("act1-")
    assert identity.request_payload["permit_id"] == "pmt-action-qa-1"
    assert (
        identity.request_payload["action_payload_hash"]
        == _action_model().action_payload_hash
    )


# Admission gates.


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "wallet_mismatch",
            "overrides": {},
            "wallet": "agt-other",
            "key": "key-action-1",
            "reason": "permit_wallet_mismatch",
        },
        {
            "name": "key_mismatch",
            "overrides": {},
            "wallet": "agt-action-subject",
            "key": "key-other",
            "reason": "permit_key_mismatch",
        },
        {
            "name": "unbound_key_call_rejected",
            "overrides": {},
            "wallet": "agt-action-subject",
            "key": None,
            "reason": "permit_key_mismatch",
        },
        {
            "name": "revoked",
            "overrides": {"status": "revoked"},
            "wallet": "agt-action-subject",
            "key": "key-action-1",
            "reason": "permit_revoked",
        },
        {
            "name": "payload_mismatch",
            "overrides": {},
            "wallet": "agt-action-subject",
            "key": "key-action-1",
            "arguments": {"amount_minor": 2, "recipient": "alice"},
            "reason": "action_payload_mismatch",
        },
        {
            "name": "scope_missing",
            "overrides": {"scopes_json": '["billing:charge"]'},
            "wallet": "agt-action-subject",
            "key": "key-action-1",
            "reason": "permit_scope_missing",
        },
    ],
)
async def test_validate_action_denies_without_consuming(monkeypatch, case):
    _mock_signature(monkeypatch, True)
    model = _action_model(**case["overrides"])
    result = await validate_action_request(
        model,
        BINDING,
        case["wallet"],
        case["key"],
        case.get("arguments", dict(DEFAULT_ARGS)),
        "admission",
    )
    assert result.allowed is False
    assert result.reason == case["reason"]
    assert result.permit is model


@pytest.mark.anyio
async def test_validate_action_rejects_bad_signature(monkeypatch):
    _mock_signature(monkeypatch, False)
    model = _action_model()
    result = await validate_action_request(
        model,
        BINDING,
        model.subject_wallet_id,
        model.subject_key_id,
        dict(DEFAULT_ARGS),
        "admission",
    )
    assert result.allowed is False
    assert result.reason == "permit_signature_invalid"


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["admission", "replay"])
async def test_validate_action_happy_path(monkeypatch, phase):
    _mock_signature(monkeypatch, True)
    model = _action_model()
    result = await validate_action_request(
        model,
        BINDING,
        model.subject_wallet_id,
        model.subject_key_id,
        dict(DEFAULT_ARGS),
        phase,
    )
    assert result.allowed is True
    assert result.reason is None


@pytest.mark.anyio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "bug: validate_action_request ignores phase, so durable replay of a "
        "prior action is denied after expiry instead of returning its "
        "evidence (app/services/action_permits.py)"
    ),
)
async def test_replay_after_expiry_returns_prior_evidence(monkeypatch):
    _mock_signature(monkeypatch, True)
    model = _action_model(expires_at=utc_now() - timedelta(minutes=1))
    result = await validate_action_request(
        model,
        BINDING,
        model.subject_wallet_id,
        model.subject_key_id,
        dict(DEFAULT_ARGS),
        "replay",
    )
    assert result.allowed is True


# Permit helper units (app/services/permits.py, no database).


def test_find_forbidden_field_walks_nested_arguments():
    from app.services.permits import _find_forbidden_field

    forbidden = {"secret_token"}
    assert (
        _find_forbidden_field({"note": {"secret_token": "x"}}, forbidden)
        == "secret_token"
    )
    assert (
        _find_forbidden_field({"items": [{"secret_token": 1}]}, forbidden)
        == "secret_token"
    )
    assert _find_forbidden_field({"note": "secret_token"}, forbidden) is None
    assert _find_forbidden_field({"note": "fine"}, forbidden) is None


def test_permit_constraints_snapshot_normalizes_cap():
    from app.services.permits import permit_constraints_snapshot

    model = _base_model(
        max_calls_per_tool_json=json.dumps({"tool-a": 2}),
        aggregate_value_cap=Decimal("10.00"),
        forbidden_fields_json=json.dumps(["secret_token"]),
        recipient_domain="partner.example",
    )
    assert permit_constraints_snapshot(model) == {
        "max_calls_per_tool": {"tool-a": 2},
        "aggregate_value_cap": "10",
        "forbidden_fields": ["secret_token"],
        "recipient_domain": "partner.example",
    }
    assert permit_constraints_snapshot(_base_model()) == {}


# Receipt reads (app/services/receipts.py).


@pytest.mark.anyio
async def test_get_receipt_by_ledger_entry_id(clean_database):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.services.receipts import get_receipt_service
    from tests.test_trust_helpers import (
        create_tool_permit,
        provision_agent_wallet,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        provisioned = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="ledger-lookup-tool",
            idem_key="ledger-lookup-permit",
        )
        from app.db.database import get_session_factory
        from app.db.models import LedgerEntryModel

        async with get_session_factory()() as session:
            session.add(
                LedgerEntryModel(
                    entry_id="le-qa-lookup-1",
                    wallet_id=provisioned["agent_wallet_id"],
                    action="charge",
                    amount=Decimal("1"),
                    balance_after=Decimal("999"),
                )
            )
            await session.commit()
        service = get_receipt_service()
        receipt = await service.create_receipt(
            permit_id=permit["permit_id"],
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool="ledger-lookup-tool",
            request_payload={"n": 1},
            response_payload={"ok": True},
            ledger_entry_id="le-qa-lookup-1",
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("1"),
            outcome="success",
            audit_event_id=None,
        )
        found = await service.get_receipt_by_ledger_entry_id("le-qa-lookup-1")
        assert found is not None
        assert found.receipt_id == receipt.receipt_id
        assert await service.get_receipt_by_ledger_entry_id("le-missing") is None


@pytest.mark.anyio
async def test_receipt_prepared_signing_key_requires_session():
    from app.services.receipts import ReceiptError, get_receipt_service

    with pytest.raises(
        ReceiptError, match="receipt_prepared_signing_key_requires_session"
    ):
        await get_receipt_service().create_receipt(
            permit_id="permit-missing",
            wallet_id="wallet-missing",
            key_id=None,
            tool="tool-missing",
            request_payload={"n": 1},
            response_payload=None,
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="denied",
            audit_event_id=None,
            prepared_signing_key_id="sk-missing",
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload,request_hash",
    [
        ({"n": 1}, "a" * 64),
        (None, None),
    ],
)
async def test_receipt_request_identity_needs_exactly_one(payload, request_hash):
    from app.services.receipts import ReceiptError, get_receipt_service

    with pytest.raises(ReceiptError, match="receipt_request_identity_invalid"):
        await get_receipt_service().create_receipt(
            permit_id="permit-missing",
            wallet_id="wallet-missing",
            key_id=None,
            tool="tool-missing",
            request_payload=payload,
            response_payload=None,
            ledger_entry_id=None,
            credits_authorized=Decimal("1"),
            credits_charged=Decimal("0"),
            outcome="denied",
            audit_event_id=None,
            request_hash=request_hash,
        )
