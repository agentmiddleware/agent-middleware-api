"""Request-body boundaries for permits, billing, and API keys.

These tests pin values that used to pass schema validation and then fail
later: a boolean coerced into money or a key limit, a string longer than
the database column, a NUL byte Postgres rejects, a Unicode spelling of a
forbidden field, and an argument tree deep enough to blow the stack.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.billing import (
    CreateAPIKeyRequest,
    CreateAgentWalletRequest,
    CreateChildWalletRequest,
    CreateSponsorWalletRequest,
    EmergencyKeyRevocationRequest,
    RegisterServiceRequest,
    RotateAPIKeyRequest,
    ServiceCategory,
    TopUpRequest,
)
from app.schemas.trust import (
    ActionPermitCreateRequest,
    PermitCreateRequest,
    PermitRequestCreate,
    PermitVerifyRequest,
    QuoteCreateRequest,
)
from app.services.permits import _find_forbidden_field, recipient_binding_matches
from app.routers.dev_keys import SelfProvisionRequest

_WHEN = datetime(2030, 1, 1, tzinfo=timezone.utc)
_FULLWIDTH_PASSWORD = "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44"


def _nested(depth: int) -> dict:
    node: dict = {"leaf": 1}
    for _ in range(depth):
        node = {"child": node}
    return node


def _permit(**overrides):
    payload = {
        "issuer_wallet_id": "issuer",
        "subject_wallet_id": "subject",
        "max_credits": Decimal("1"),
        "expires_at": _WHEN,
    }
    payload.update(overrides)
    return PermitCreateRequest(**payload)


def _action(**overrides):
    payload = {
        "issuer_wallet_id": "issuer",
        "subject_wallet_id": "subject",
        "max_credits": Decimal("1"),
        "expires_at": _WHEN,
        "tool_name": "lookup",
        "arguments": {"q": "ok"},
    }
    payload.update(overrides)
    return ActionPermitCreateRequest(**payload)


def test_emergency_reason_must_fit_with_its_prefix():
    # "EMERGENCY: " is 11 characters. 245 more is 256 and does not fit
    # revoke_reason VARCHAR(255). 244 fits exactly.
    EmergencyKeyRevocationRequest(wallet_id="wallet", reason="r" * 244)
    with pytest.raises(ValidationError):
        EmergencyKeyRevocationRequest(wallet_id="wallet", reason="r" * 245)
    with pytest.raises(ValidationError):
        EmergencyKeyRevocationRequest(wallet_id="wallet", reason="bad\x00reason")
    with pytest.raises(ValidationError):
        EmergencyKeyRevocationRequest(wallet_id="wallet", reason="r" * 1_000_000)


def test_rotate_reason_rejects_nul_and_keeps_column_length():
    RotateAPIKeyRequest(wallet_id="wallet", reason="r" * 255)
    with pytest.raises(ValidationError):
        RotateAPIKeyRequest(wallet_id="wallet", reason="r" * 256)
    with pytest.raises(ValidationError):
        RotateAPIKeyRequest(wallet_id="wallet", reason="bad\x00reason")


def test_api_key_limits_reject_booleans_and_unstorable_bounds():
    CreateAPIKeyRequest(wallet_id="wallet", expires_in_days=30)
    CreateAPIKeyRequest(wallet_id="wallet", expires_in_days="30")
    CreateAPIKeyRequest(wallet_id="wallet", expires_in_days=" 30 ")
    CreateAPIKeyRequest(wallet_id="wallet", expires_in_days=2_000_000)
    CreateAPIKeyRequest(wallet_id="wallet", max_uses=2_147_483_647)
    CreateAPIKeyRequest(wallet_id="wallet", key_name="")

    for bad in (
        {"expires_in_days": True},
        {"expires_in_days": 10**7},
        {"expires_in_days": "10000000"},
        {"max_uses": True},
        {"max_uses": 2**31},
        {"max_uses": "2147483648"},
        {"wallet_id": "w" * 51},
        {"key_name": "bad\x00name"},
        {"expires_in_days": {"days": 30}},
    ):
        payload = {"wallet_id": "wallet"}
        payload.update(bad)
        with pytest.raises(ValidationError):
            CreateAPIKeyRequest(**payload)

    with pytest.raises(ValidationError):
        CreateAPIKeyRequest(wallet_id=None)


def test_direct_key_helpers_reject_limits_and_revoke_reasons():
    from app.services.api_key_service import (
        stored_revoke_reason,
        validate_api_key_limits,
    )

    validate_api_key_limits(None, None)
    validate_api_key_limits(30, 1)
    validate_api_key_limits(2_000_000, 2_147_483_647)

    with pytest.raises(ValueError):
        validate_api_key_limits(True, None)
    with pytest.raises(ValueError):
        validate_api_key_limits(10**7, None)
    with pytest.raises(ValueError):
        validate_api_key_limits(None, 2**31)
    with pytest.raises(ValueError):
        validate_api_key_limits(0, None)

    stored = stored_revoke_reason("r" * 244, emergency=True)
    assert stored == "EMERGENCY: " + ("r" * 244)
    assert len(stored) == 255
    assert stored_revoke_reason("user_request") == "user_request"
    assert stored_revoke_reason("r" * 255) == "r" * 255

    with pytest.raises(ValueError):
        stored_revoke_reason("r" * 245, emergency=True)
    with pytest.raises(ValueError):
        stored_revoke_reason("bad\x00reason", emergency=True)
    with pytest.raises(ValueError):
        stored_revoke_reason("r" * 256)
    with pytest.raises(ValueError):
        stored_revoke_reason("bad\x00reason")


def test_revoke_query_rejects_reason_longer_than_column(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.auth import AuthContext, get_auth_context
    from app.routers import api_keys as api_keys_router

    class _Keys:
        def __init__(self) -> None:
            self.calls = 0

        async def revoke_key(self, wallet_id, key_id, reason):
            self.calls += 1
            return True

    keys = _Keys()
    monkeypatch.setattr(api_keys_router, "get_api_key_service", lambda: keys)
    app = FastAPI()
    app.include_router(api_keys_router.router)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        source="test",
        raw_key="test-key",
        is_bootstrap_admin=True,
    )
    client = TestClient(app)
    response = client.delete(
        "/v1/api-keys/wallet/key",
        params={"reason": "r" * 256},
    )
    assert response.status_code == 422
    assert keys.calls == 0

    from fastapi import HTTPException

    from app.routers.api_keys import _reject_unstorable_revoke_reason

    with pytest.raises(HTTPException) as caught:
        _reject_unstorable_revoke_reason("bad\x00reason")
    assert caught.value.status_code == 422


def test_money_fields_reject_booleans_and_unstorable_amounts():
    CreateSponsorWalletRequest(sponsor_name="Acme", email="a@b.co", initial_credits=0)
    CreateSponsorWalletRequest(sponsor_name="Acme", email="a@b.co")
    CreateAgentWalletRequest(
        sponsor_wallet_id="sponsor",
        agent_id="agent",
        budget_credits=0.1,
        daily_limit=0,
    )
    CreateAgentWalletRequest(
        sponsor_wallet_id="sponsor",
        agent_id="agent",
        budget_credits="10.5",
        daily_limit=None,
        auto_refill_threshold=1e-8,
        auto_refill_amount=1000,
    )
    SelfProvisionRequest(budget_credits=0)
    SelfProvisionRequest(budget_credits=1e-8)
    RegisterServiceRequest(
        name="lookup",
        category=ServiceCategory.ORACLE,
        credits_per_unit="1.5",
    )
    TopUpRequest(wallet_id="sponsor", amount_fiat="10.5")

    with pytest.raises(ValidationError):
        CreateAgentWalletRequest(
            sponsor_wallet_id="sponsor",
            agent_id="agent",
            budget_credits=True,
        )
    with pytest.raises(ValidationError):
        CreateAgentWalletRequest(
            sponsor_wallet_id="sponsor",
            agent_id="agent",
            budget_credits=1e-9,
        )
    with pytest.raises(ValidationError):
        CreateAgentWalletRequest(
            sponsor_wallet_id="sponsor",
            agent_id="agent",
            budget_credits=999999999999.99,
        )
    with pytest.raises(ValidationError):
        CreateSponsorWalletRequest(
            sponsor_name="Acme",
            email="a@b.co",
            initial_credits=True,
        )
    with pytest.raises(ValidationError):
        CreateChildWalletRequest(
            parent_wallet_id="parent",
            child_agent_id="child",
            budget_credits=True,
            max_spend=1,
        )
    with pytest.raises(ValidationError):
        SelfProvisionRequest(budget_credits=True)
    with pytest.raises(ValidationError):
        SelfProvisionRequest(budget_credits=1e-9)
    with pytest.raises(ValidationError):
        RegisterServiceRequest(
            name="lookup",
            category=ServiceCategory.ORACLE,
            credits_per_unit=True,
        )
    with pytest.raises(ValidationError):
        TopUpRequest(wallet_id="sponsor", amount_fiat=True)


def test_stored_strings_reject_column_overflow_and_nul():
    CreateSponsorWalletRequest(sponsor_name="Acme", email="e" * 255)
    CreateSponsorWalletRequest(sponsor_name="Acme", email="")
    CreateAgentWalletRequest(
        sponsor_wallet_id="s" * 50,
        agent_id="a" * 100,
        budget_credits=1,
    )
    CreateChildWalletRequest(
        parent_wallet_id="p" * 50,
        child_agent_id="c" * 100,
        budget_credits=1,
        max_spend=1,
        task_description="t" * 500,
    )
    _permit(recipient_domain="d" * 255)

    with pytest.raises(ValidationError):
        CreateSponsorWalletRequest(sponsor_name="Acme", email="e" * 256)
    with pytest.raises(ValidationError):
        CreateSponsorWalletRequest(sponsor_name="Acme", email="e" * 1_000_000)
    with pytest.raises(ValidationError):
        CreateSponsorWalletRequest(sponsor_name="Acme", email="a\x00b")
    with pytest.raises(ValidationError):
        CreateSponsorWalletRequest(sponsor_name="bad\x00name", email="a@b.co")
    with pytest.raises(ValidationError):
        CreateAgentWalletRequest(
            sponsor_wallet_id="sponsor",
            agent_id="a" * 101,
            budget_credits=1,
        )
    with pytest.raises(ValidationError):
        CreateAgentWalletRequest(
            sponsor_wallet_id="sponsor",
            agent_id="bad\x00id",
            budget_credits=1,
        )
    with pytest.raises(ValidationError):
        CreateAgentWalletRequest(
            sponsor_wallet_id="sponsor",
            agent_id="",
            budget_credits=1,
        )
    with pytest.raises(ValidationError):
        CreateChildWalletRequest(
            parent_wallet_id="parent",
            child_agent_id="c" * 101,
            budget_credits=1,
            max_spend=1,
        )
    with pytest.raises(ValidationError):
        CreateChildWalletRequest(
            parent_wallet_id="parent",
            child_agent_id="bad\x00id",
            budget_credits=1,
            max_spend=1,
        )
    with pytest.raises(ValidationError):
        CreateChildWalletRequest(
            parent_wallet_id="parent",
            child_agent_id="child",
            budget_credits=1,
            max_spend=1,
            task_description="t" * 501,
        )
    with pytest.raises(ValidationError):
        CreateChildWalletRequest(
            parent_wallet_id="parent",
            child_agent_id="child",
            budget_credits=1,
            max_spend=1,
            task_description="bad\x00task",
        )
    with pytest.raises(ValidationError):
        _permit(recipient_domain="d" * 256)
    with pytest.raises(ValidationError):
        _permit(recipient_domain="bad\x00domain")
    _permit(recipient_domain=None)


def test_tool_names_match_receipt_column():
    QuoteCreateRequest(wallet_id="wallet", tool="lookup")
    _permit(allowed_tools=["lookup"])
    PermitRequestCreate(
        issuer_wallet_id="issuer",
        subject_wallet_id="subject",
        allowed_tools=["lookup"],
        max_credits=Decimal("1"),
        expires_at=_WHEN,
        justification="need access",
    )
    with pytest.raises(ValidationError):
        PermitRequestCreate(
            issuer_wallet_id="issuer",
            subject_wallet_id="subject",
            allowed_tools=["lookup"],
            max_credits=Decimal("1"),
            expires_at=_WHEN,
            justification="bad\x00why",
        )
    _action(tool_name="t" * 128)

    with pytest.raises(ValidationError):
        QuoteCreateRequest(wallet_id="wallet", tool="")
    with pytest.raises(ValidationError):
        QuoteCreateRequest(wallet_id="wallet", tool="t" * 129)
    with pytest.raises(ValidationError):
        QuoteCreateRequest(wallet_id="wallet", tool="bad\x00tool")
    with pytest.raises(ValidationError):
        _permit(allowed_tools=[""])
    with pytest.raises(ValidationError):
        _permit(allowed_tools=["t" * 129])
    with pytest.raises(ValidationError):
        _action(tool_name="t" * 200)
    with pytest.raises(ValidationError):
        _permit(issuer_wallet_id="w" * 51)
    with pytest.raises(ValidationError):
        _permit(forbidden_fields=["f" * 257])
    with pytest.raises(ValidationError):
        _permit(forbidden_fields=["bad\x00field"])
    _permit(forbidden_fields=["f" * 256])


def test_verify_estimate_rejects_scale_the_column_cannot_keep():
    PermitVerifyRequest(permit_id="permit")
    PermitVerifyRequest(permit_id="permit", estimated_credits=0)
    PermitVerifyRequest(permit_id="permit", estimated_credits="1.5")
    PermitVerifyRequest(permit_id="permit", estimated_credits=Decimal("0.1"))

    with pytest.raises(ValidationError):
        PermitVerifyRequest(permit_id="permit", estimated_credits="0.123456789")
    with pytest.raises(ValidationError):
        PermitVerifyRequest(permit_id="permit", estimated_credits=-1)
    with pytest.raises(ValidationError):
        PermitVerifyRequest(permit_id="permit", estimated_credits=True)


def test_forbidden_field_match_folds_compatible_unicode_only():
    nfd = "cafe\u0301"
    nfc = "caf\u00e9"
    assert _find_forbidden_field({nfd: "x"}, {nfc}) == nfd
    assert _find_forbidden_field({"outer": {nfd: 1}}, {nfc}) == nfd
    assert _find_forbidden_field({_FULLWIDTH_PASSWORD: "x"}, {"password"}) == (
        _FULLWIDTH_PASSWORD
    )
    assert _find_forbidden_field({"token": 1}, {"token"}) == "token"
    assert _find_forbidden_field({"ok": 1}, {"token"}) is None
    # Greek omicron is a different letter. It must not match Latin "token".
    assert _find_forbidden_field({"t\u03bfken": "x"}, {"token"}) is None


def test_recipient_binding_matches_equivalent_unicode_hosts():
    assert (
        recipient_binding_matches(
            "caf\u00e9.example",
            "https://cafe\u0301.example/pay",
        )
        is True
    )
    assert recipient_binding_matches("cafe\u0301.example", "caf\u00e9.example") is True
    assert recipient_binding_matches(None, "https://partner.example/pay") is True
    assert (
        recipient_binding_matches(
            "partner.example",
            "https://partner.example/tools/call",
        )
        is True
    )
    assert (
        recipient_binding_matches("allowed.example.com", "https://other.example")
        is False
    )


def test_action_arguments_reject_deep_nesting():
    _action(arguments=_nested(32))
    with pytest.raises(ValidationError):
        _action(arguments=_nested(40))

    from app.services.action_permits import _strict_json

    _strict_json(_nested(32))
    with pytest.raises(ValueError, match="json_too_deep"):
        _strict_json(_nested(40))


def test_extra_balance_field_is_not_applied():
    wallet = CreateSponsorWalletRequest(
        sponsor_name="Acme",
        email="a@b.co",
        balance=1_000_000,
    )
    assert wallet.initial_credits == 0.0
    assert "balance" not in wallet.model_dump()


def test_child_ttl_string_still_coerces_and_bool_does_not():
    child = CreateChildWalletRequest(
        parent_wallet_id="parent",
        child_agent_id="child",
        budget_credits=1,
        max_spend=1,
        ttl_seconds="10",
    )
    assert child.ttl_seconds == 10
    with pytest.raises(ValidationError):
        CreateChildWalletRequest(
            parent_wallet_id="parent",
            child_agent_id="child",
            budget_credits=1,
            max_spend=1,
            ttl_seconds=True,
        )


def test_required_permit_fields_still_reject_null():
    with pytest.raises(ValidationError):
        _permit(max_credits=None)
    future = _WHEN + timedelta(days=1)
    permit = _permit(expires_at=future, allowed_tools=["lookup"])
    assert permit.allowed_tools == ["lookup"]
