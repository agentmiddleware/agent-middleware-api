"""Focused tests for app.services.webauthn_provider.WebAuthnProvider."""

import pytest

from app.core.time import utc_now
from app.services.webauthn_provider import (
    ChallengeStatus,
    VerificationRecord,
    WebAuthnProvider,
)


@pytest.fixture
def provider():
    return WebAuthnProvider(
        rp_id="test.example.com",
        rp_name="Test App",
        challenge_expiry_seconds=60,
        verification_validity_seconds=60,
    )


@pytest.fixture
def mock_allowed(monkeypatch):
    # py_webauthn is not installed in this environment, so the provider
    # fails closed unless tests explicitly opt into the mock path.
    monkeypatch.setenv("WEBAUTHN_ALLOW_MOCK", "true")


def _credential(credential_id="test-credential-id"):
    return {
        "id": credential_id,
        "raw_id": credential_id,
        "type": "public-key",
        "response": {
            "authenticator_data": "dGVzdA==",
            "client_data_json": '{"type":"webauthn.get"}',
            "signature": "dGVzdA==",
        },
    }


async def test_requires_passkey_is_case_insensitive(provider):
    assert await provider.requires_passkey("s1", "checkout") is True
    assert await provider.requires_passkey("s1", "Checkout") is True
    assert await provider.requires_passkey("s1", "PAYMENT") is True
    assert await provider.requires_passkey("s1", "navigate_to") is False


async def test_create_challenge_stores_pending_challenge(provider):
    options = await provider.create_challenge(session_id="s1", action="checkout")

    assert options["challenge_id"]
    assert options["rp_id"] == "test.example.com"
    assert options["timeout"] == 60000
    stored = provider.get_challenge(options["challenge_id"])
    assert stored is not None
    assert stored.status == ChallengeStatus.PENDING
    assert stored.session_id == "s1"
    assert stored.user_verification == "required"


async def test_create_challenge_rejects_low_risk_action(provider):
    with pytest.raises(ValueError, match="does not require passkey"):
        await provider.create_challenge(session_id="s1", action="navigate_to")


async def test_create_challenge_lists_registered_credentials_for_user(provider):
    await provider.register_credential("user-1", "cred-1", b"pk-1")
    await provider.register_credential("user-2", "cred-2", b"pk-2")

    options = await provider.create_challenge(
        session_id="s1", action="checkout", user_id="user-1"
    )
    ids = [c["id"] for c in options["allow_credentials"]]
    assert ids == ["cred-1"]


async def test_verify_response_unknown_challenge(provider, mock_allowed):
    with pytest.raises(ValueError, match="Challenge not found"):
        await provider.verify_response("no-such-id", _credential())


async def test_verify_response_missing_credential_id(provider, mock_allowed):
    options = await provider.create_challenge(session_id="s1", action="checkout")
    with pytest.raises(ValueError, match="Missing credential ID"):
        await provider.verify_response(options["challenge_id"], {"type": "public-key"})


async def test_verify_success_marks_action_verified(provider, mock_allowed):
    options = await provider.create_challenge(session_id="s1", action="checkout")
    result = await provider.verify_response(options["challenge_id"], _credential())

    assert result["verified"] is True
    assert result["session_id"] == "s1"
    assert await provider.is_action_verified("s1", "checkout") is True
    assert await provider.is_action_verified("s1", "payment") is False

    status = await provider.get_verification_status("s1", "checkout")
    assert status["is_verified"] is True
    assert status["expires_in_seconds"] is not None


async def test_verify_response_rejects_replay_of_verified_challenge(
    provider, mock_allowed
):
    options = await provider.create_challenge(session_id="s1", action="checkout")
    await provider.verify_response(options["challenge_id"], _credential())

    with pytest.raises(ValueError, match="already verified"):
        await provider.verify_response(options["challenge_id"], _credential())


async def test_verify_fails_closed_without_library_or_mock(provider, monkeypatch):
    monkeypatch.setenv("WEBAUTHN_ALLOW_MOCK", "false")
    options = await provider.create_challenge(session_id="s1", action="checkout")

    with pytest.raises(ValueError, match="Credential verification failed"):
        await provider.verify_response(options["challenge_id"], _credential())

    assert await provider.is_action_verified("s1", "checkout") is False
    with pytest.raises(ValueError, match="previously failed"):
        await provider.verify_response(options["challenge_id"], _credential())


async def test_expired_verification_reads_as_unverified(provider, mock_allowed):
    options = await provider.create_challenge(session_id="s1", action="checkout")
    await provider.verify_response(options["challenge_id"], _credential())

    key = provider._make_verification_key("s1", "checkout")
    provider._verifications[key].expires_at = utc_now()

    assert await provider.is_action_verified("s1", "checkout") is False
    status = await provider.get_verification_status("s1", "checkout")
    assert status["is_verified"] is False


async def test_invalidate_single_action_then_all(provider, mock_allowed):
    for action in ("checkout", "payment"):
        options = await provider.create_challenge(session_id="s1", action=action)
        await provider.verify_response(options["challenge_id"], _credential())

    assert await provider.invalidate_verification("s1", "checkout") == 1
    assert await provider.invalidate_verification("s1", "checkout") == 0
    assert await provider.is_action_verified("s1", "payment") is True
    assert await provider.invalidate_verification("s1") == 1
    assert await provider.is_action_verified("s1", "payment") is False


async def test_register_and_list_credentials_filters_by_user(provider):
    await provider.register_credential("user-1", "cred-1", b"pk-1", name="laptop")
    await provider.register_credential("user-2", "cred-2", b"pk-2")

    all_creds = provider.get_registered_credentials()
    assert {c["credential_id"] for c in all_creds} == {"cred-1", "cred-2"}
    mine = provider.get_registered_credentials("user-1")
    assert [c["credential_id"] for c in mine] == ["cred-1"]
    assert mine[0]["name"] == "laptop"


def test_cleanup_expired_removes_stale_items(provider):
    provider._challenge_expiry = -1
    import asyncio

    challenge_id = asyncio.run(provider.create_challenge("s1", "checkout"))[
        "challenge_id"
    ]
    key = provider._make_verification_key("s1", "checkout")
    provider._verifications[key] = VerificationRecord(
        session_id="s1",
        action="checkout",
        verified_at=utc_now(),
        expires_at=utc_now(),
        credential_id="cred-1",
    )

    removed = provider.cleanup_expired()
    assert removed == {"challenges_removed": 1, "verifications_removed": 1}
    assert provider.get_challenge(challenge_id) is None


def test_high_risk_actions_sorted_and_challenge_lookup_miss(provider):
    actions = provider.get_high_risk_actions()
    assert actions == sorted(actions)
    assert "checkout" in actions
    assert provider.get_challenge("no-such-id") is None
