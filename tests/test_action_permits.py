"""Strict single-action authority and legacy signature compatibility."""

from dataclasses import replace
from decimal import Decimal

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from app.schemas.trust import ActionPermitFields
from app.services.action_permits import (
    ActionToolBinding,
    action_payload_hash,
    canonical_action_payload,
)
from app.services.permits import PermitService
from app.services.signing_keys import canonical_json
from tests.test_permit_signing_input_snapshot import _base_model


MONEY_SCHEMA = {
    "type": "object",
    "properties": {
        "amount_minor": {"type": "integer"},
        "recipient": {"type": "string"},
        "currency": {"type": "string", "default": "USD"},
    },
    "required": ["amount_minor", "recipient"],
    "additionalProperties": False,
}
BINDING = ActionToolBinding(
    "test-plane", "partner.pay", "a" * 64, "money", "1", MONEY_SCHEMA
)
FIELDS = dict(
    action_contract_version=1,
    action_payload_hash="b" * 64,
    action_schema_id="money",
    action_schema_version="1",
    action_public_tool_id="partner.pay",
    action_upstream_binding_hash="a" * 64,
)


def test_strict_action_digest():
    args = {"amount_minor": 1, "recipient": "alice"}
    digest = action_payload_hash(BINDING, "wallet", args)
    assert digest == action_payload_hash(
        BINDING, "wallet", dict(reversed(list(args.items())))
    )
    assert digest == action_payload_hash(BINDING, "wallet", {**args, "currency": "USD"})
    for changed in ({**args, "recipient": "bob"}, {**args, "amount_minor": 2}):
        assert digest != action_payload_hash(BINDING, "wallet", changed)
    for value in ("1", True, 1.0, float("nan"), float("inf"), Decimal("1"), object()):
        with pytest.raises(ValueError):
            action_payload_hash(BINDING, "wallet", {**args, "amount_minor": value})
    with pytest.raises(ValueError):
        action_payload_hash(BINDING, "wallet", {1: "bad", **args})
    for binding in (
        replace(BINDING, public_tool_id="other"),
        replace(BINDING, schema_version="2"),
        replace(BINDING, upstream_binding_hash="c" * 64),
    ):
        assert digest != action_payload_hash(binding, "wallet", args)
    assert digest != action_payload_hash(BINDING, "other-wallet", args)
    assert '"currency":"USD"' in canonical_action_payload(BINDING, "wallet", args)


def test_number_representations_remain_distinct():
    binding = replace(
        BINDING,
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
        },
    )
    assert action_payload_hash(binding, "wallet", {"value": 1}) != action_payload_hash(
        binding, "wallet", {"value": 1.0}
    )
    with pytest.raises(ValueError):
        action_payload_hash(binding, "wallet", {"value": "1"})


def test_action_fields_all_or_none():
    assert ActionPermitFields().model_dump() == dict.fromkeys(FIELDS)
    assert ActionPermitFields(**FIELDS).action_contract_version == 1
    for field in FIELDS:
        with pytest.raises(ValidationError):
            ActionPermitFields(**{k: v for k, v in FIELDS.items() if k != field})
    for version in (2, True, "1"):
        with pytest.raises(ValidationError):
            ActionPermitFields(**{**FIELDS, "action_contract_version": version})
    with pytest.raises(ValidationError):
        ActionPermitFields(**{**FIELDS, "action_payload_hash": "bad"})
    with pytest.raises(ValueError):
        PermitService._unsigned_payload(_base_model(action_contract_version=1))


def test_action_signature_covers_every_binding_field():
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    model = _base_model(**FIELDS)
    payload = PermitService._verification_payload(model)
    assert all(payload[field] == value for field, value in FIELDS.items())
    signature = key.sign(canonical_json(payload).encode())
    key.public_key().verify(signature, canonical_json(payload).encode())
    for field in FIELDS:
        tampered = dict(payload)
        tampered[field] = 2 if field == "action_contract_version" else "changed"
        with pytest.raises(InvalidSignature):
            key.public_key().verify(signature, canonical_json(tampered).encode())
    legacy = PermitService._unsigned_payload(_base_model())
    assert not set(FIELDS).intersection(legacy)


@pytest.mark.parametrize(
    "invalid",
    [
        {"oneOf": []},
        {"format": "email"},
        {"pattern": ".*"},
        {"additionalProperties": {"type": "string"}},
    ],
)
def test_unsupported_schema_rejects(invalid):
    schema = {**MONEY_SCHEMA, **invalid}
    with pytest.raises(ValueError):
        action_payload_hash(
            replace(BINDING, input_schema=schema),
            "wallet",
            {"amount_minor": 1, "recipient": "alice"},
        )


def test_nested_defaults_constraints_and_raw_json_rejection():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "integer", "minimum": 1, "maximum": 3},
                        "currency": {
                            "type": "string",
                            "default": "USD",
                            "enum": ["USD"],
                        },
                    },
                    "required": ["amount"],
                },
            }
        },
        "required": ["items"],
    }
    binding = replace(BINDING, input_schema=schema)
    original = {"items": [{"amount": 1}]}
    assert action_payload_hash(binding, "wallet", original) == action_payload_hash(
        binding, "wallet", {"items": [{"amount": 1, "currency": "USD"}]}
    )
    assert original == {"items": [{"amount": 1}]}
    for invalid in (
        {"items": []},
        {"items": [{"amount": 0}]},
        {"items": [{"amount": 1, "currency": "EUR"}]},
        {"items": [{"amount": 1, "other": None}]},
        {"items": [{"amount": 1}], "extra": object()},
    ):
        with pytest.raises(ValueError):
            action_payload_hash(binding, "wallet", invalid)
    invalid_default = {
        "type": "object",
        "properties": {"value": {"type": "integer", "default": "1"}},
    }
    with pytest.raises(ValueError):
        action_payload_hash(
            replace(BINDING, input_schema=invalid_default), "wallet", {}
        )


@pytest.mark.anyio
async def test_generic_service_action_issuance_is_closed():
    from datetime import datetime, timedelta, timezone
    from app.schemas.trust import PermitCreateRequest
    from app.services.permits import PermitError

    request = PermitCreateRequest(
        issuer_wallet_id="issuer",
        subject_wallet_id="subject",
        max_credits=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        **FIELDS,
    )
    with pytest.raises(PermitError, match="action_permit_requires_trusted_issuance"):
        await PermitService().create_permit(request)


@pytest.mark.anyio
@pytest.mark.parametrize("stored_window_null", [False, True])
async def test_historical_envelope_issuance_record_replays(
    clean_database, stored_window_null
):
    from datetime import datetime, timedelta, timezone
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select
    from app.db.database import get_session_factory
    from app.db.models import PermitModel
    from app.main import app
    from app.schemas.trust import PermitCreateRequest
    from app.services.idempotency import get_idempotency_service
    from app.services.signing_keys import sha256_hex
    from tests.test_trust_helpers import provision_agent_wallet

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        wallet = await provision_agent_wallet(client)
        payload = dict(
            issuer_wallet_id=wallet["agent_wallet_id"],
            subject_wallet_id=wallet["agent_wallet_id"],
            subject_key_id=wallet["key_id"],
            allowed_tools=["historical-echo"],
            max_credits=10,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        request = PermitCreateRequest(**payload)
        permit = await PermitService().create_permit(request)
        historical_payload = request.model_dump(mode="json", exclude=set(FIELDS))
        if not stored_window_null:
            historical_payload.pop("repeat_window_seconds")
        historical_response = permit.model_dump(mode="json", exclude=set(FIELDS))
        identity = dict(
            wallet_id=wallet["agent_wallet_id"],
            endpoint="/v1/permits",
            idempotency_key="historical-envelope",
        )
        idem = get_idempotency_service()
        await idem.begin(**identity, request_payload=historical_payload)
        await idem.complete(
            **identity,
            response_reference=permit.permit_id,
            response_json=historical_response,
            status_code=201,
        )
        headers = {
            **wallet["agent_headers"],
            "Idempotency-Key": identity["idempotency_key"],
        }
        for explicit_null in (False, True):
            replay_payload = (
                {**payload, **dict.fromkeys(FIELDS)} if explicit_null else payload
            )
            replay = await client.post(
                "/v1/permits", json=replay_payload, headers=headers
            )
            assert replay.status_code == 201, replay.text
            assert replay.json()["permit_id"] == permit.permit_id
        conflict = await client.post(
            "/v1/permits", json={**payload, "max_credits": 11}, headers=headers
        )
        assert conflict.status_code == 409
        record = await idem.get_record(**identity)
        assert record.request_hash == sha256_hex(historical_payload)
        async with get_session_factory()() as session:
            assert (
                len(list((await session.execute(select(PermitModel))).scalars())) == 1
            )
        action = await client.post(
            "/v1/permits",
            json={**payload, **FIELDS},
            headers={**headers, "Idempotency-Key": "action-input-refused"},
        )
        assert action.status_code == 400
        assert action.json()["detail"] == "action_permit_requires_trusted_issuance"
        assert (
            await idem.get_record(
                **{**identity, "idempotency_key": "action-input-refused"}
            )
            is None
        )
