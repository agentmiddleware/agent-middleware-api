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
