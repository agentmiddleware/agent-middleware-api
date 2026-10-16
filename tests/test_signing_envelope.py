"""Bounded signing envelope for payloads over AWS KMS's 4096-byte RAW cap.

Under the KMS backend a canonical payload over 4096 bytes is signed as the
canonical ``{alg, kid, payload_sha256}`` envelope and the stored signature is
tagged ``Ed25519-sha256-envelope:``. Everything at or under the cap, and every
payload on the default local signer, keeps the untagged signature over the
exact payload bytes.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services import signing_keys as server
from app.services.kms_signer import KMS_MAX_RAW_MESSAGE_BYTES, KmsEd25519Signer
from app.services.signing_keys import (
    SIGNATURE_ENVELOPE_ALG,
    SigningKeyService,
    canonical_json,
    get_signing_key_service,
    sha256_hex,
)
from b2a_sdk import receipt_verifier as sdk
from b2a_sdk import verify_cli
from b2a_sdk.edge_client import LocalPermitValidator
from b2a_sdk.receipt_verifier import VerificationStatus, verify_bundle
from tests.test_kms_signer import FakeKmsClient

KID = "kms-ed25519-test"
TAG = f"{SIGNATURE_ENVELOPE_ALG}:"


def _signed_payload(padding: int) -> dict[str, Any]:
    """A receipt-shaped payload with alg/kid/payload_hash already folded in."""
    payload: dict[str, Any] = {
        "receipt_id": "rcpt-envelope",
        "tool": "big-tool",
        "constraints_evaluated": {"note": "x" * padding},
        "alg": "Ed25519",
        "kid": KID,
    }
    payload["payload_hash"] = sha256_hex(payload)
    return payload


def _big() -> dict[str, Any]:
    payload = _signed_payload(5000)
    assert len(canonical_json(payload).encode()) > KMS_MAX_RAW_MESSAGE_BYTES
    return payload


def _small() -> dict[str, Any]:
    payload = _signed_payload(100)
    assert len(canonical_json(payload).encode()) <= KMS_MAX_RAW_MESSAGE_BYTES
    return payload


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


@pytest.fixture
def kms(monkeypatch):
    service = get_signing_key_service()
    client = FakeKmsClient()
    monkeypatch.setattr(
        service, "_private_key", KmsEd25519Signer("alias/trust", client=client)
    )
    monkeypatch.setattr(service, "_key_id", KID)
    return service, client


@pytest.mark.anyio
async def test_kms_large_payload_signs_envelope_and_verifies(clean_database, kms):
    service, client = kms
    await service.ensure_active_key()
    payload = _big()

    signature, key_id, _ = await service.sign_payload_with_key_id(payload, KID)

    assert key_id == KID
    assert signature.startswith(TAG)
    # KMS only ever saw the small envelope, as pure Ed25519 over RAW bytes.
    [call] = client.sign_calls
    assert call["MessageType"] == "RAW"
    assert len(call["Message"]) <= KMS_MAX_RAW_MESSAGE_BYTES
    assert json.loads(call["Message"]) == {
        "alg": SIGNATURE_ENVELOPE_ALG,
        "kid": KID,
        "payload_sha256": sha256_hex(canonical_json(payload)),
    }
    assert await service.verify_payload(payload, signature=signature, key_id=KID)

    tampered = dict(payload, tool="other-tool")
    assert not await service.verify_payload(tampered, signature=signature, key_id=KID)
    # Stripping the tag does not turn it into a valid direct signature.
    untagged = signature.removeprefix(TAG)
    assert not await service.verify_payload(payload, signature=untagged, key_id=KID)


@pytest.mark.anyio
async def test_kms_small_payload_signature_is_unchanged(clean_database, kms):
    service, client = kms
    await service.ensure_active_key()
    payload = _small()

    signature, _, _ = await service.sign_payload_with_key_id(payload, KID)

    message = canonical_json(payload).encode()
    assert [c["Message"] for c in client.sign_calls] == [message]
    assert signature == base64.b64encode(client._private_key.sign(message)).decode()


@pytest.mark.anyio
async def test_local_signer_never_uses_envelope(clean_database):
    service = SigningKeyService()
    key = await service.ensure_active_key()
    payload = _big()

    signature, _, _ = await service.sign_payload_with_key_id(payload, key.key_id)

    assert ":" not in signature
    local_key = service._load_private_key()
    expected = local_key.sign(canonical_json(payload).encode())
    assert base64.b64decode(signature) == expected


@pytest.mark.anyio
async def test_verify_rejects_unknown_alg_and_small_payload_envelope(
    clean_database, kms
):
    service, client = kms
    await service.ensure_active_key()
    private_key = client._private_key

    big = _big()
    good, _, _ = await service.sign_payload_with_key_id(big, KID)
    encoded = good.removeprefix(TAG)
    for bad_tag in ("Ed25519-sha512-envelope", "ed25519-sha256-envelope", "", "x"):
        assert not await service.verify_payload(
            big, signature=f"{bad_tag}:{encoded}", key_id=KID
        )

    # A genuine signature over the envelope of a small payload is still refused:
    # small payloads have exactly one valid form (no downgrade confusion).
    small = _small()
    envelope = server.signature_envelope_bytes(KID, canonical_json(small).encode())
    forged = TAG + base64.b64encode(private_key.sign(envelope)).decode()
    assert not await service.verify_payload(small, signature=forged, key_id=KID)


def test_server_and_sdk_agree_on_envelope_bytes():
    signing_bytes = canonical_json(_big()).encode()
    assert sdk.SIGNATURE_ENVELOPE_ALG == server.SIGNATURE_ENVELOPE_ALG
    assert (
        sdk.SIGNATURE_ENVELOPE_THRESHOLD_BYTES
        == server.SIGNATURE_ENVELOPE_THRESHOLD_BYTES
    )
    assert sdk.signature_message(
        SIGNATURE_ENVELOPE_ALG, KID, signing_bytes
    ) == server.signature_message(SIGNATURE_ENVELOPE_ALG, KID, signing_bytes)
    assert server.split_signature("abc=") == sdk.split_signature("abc=")
    assert server.split_signature(TAG + "abc=") == sdk.split_signature(TAG + "abc=")


def _bundle(payload: dict[str, Any], signature: str) -> dict[str, Any]:
    return {
        "receipt_id": payload["receipt_id"],
        "kid": KID,
        "canonicalization": sdk.CANONICALIZATION,
        "signing_input": canonical_json(payload),
        "signature": signature,
    }


@pytest.mark.anyio
async def test_verifier_cli_handles_envelope_signature(clean_database, kms, tmp_path):
    service, client = kms
    await service.ensure_active_key()
    payload = _big()
    signature, _, _ = await service.sign_payload_with_key_id(payload, KID)
    key_set = {KID: _raw_public(client._private_key)}
    keys_doc = {
        "keys": [
            {
                "kid": KID,
                "alg": "Ed25519",
                "public_key_b64": base64.b64encode(key_set[KID]).decode(),
            }
        ]
    }
    keys_path = tmp_path / "trust-keys.json"
    keys_path.write_text(json.dumps(keys_doc))

    def run(bundle: dict[str, Any]) -> int:
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps(bundle))
        return verify_cli.main(["--bundle", str(path), "--keys", str(keys_path)])

    bundle = _bundle(payload, signature)
    result = verify_bundle(bundle, key_set)
    assert result.status is VerificationStatus.VERIFIED, result.reason
    assert run(bundle) == verify_cli.EXIT_VERIFIED

    tampered = dict(payload, tool="other-tool")
    tampered["payload_hash"] = sha256_hex(
        {k: v for k, v in tampered.items() if k != "payload_hash"}
    )
    assert verify_bundle(_bundle(tampered, signature), key_set).is_tampered
    assert run(_bundle(tampered, signature)) == verify_cli.EXIT_INVALID

    unknown = _bundle(payload, "Ed25519-v9:" + signature.removeprefix(TAG))
    assert verify_bundle(unknown, key_set).status is VerificationStatus.MALFORMED
    assert run(unknown) == verify_cli.EXIT_UNDETERMINED

    small = _small()
    envelope = server.signature_envelope_bytes(KID, canonical_json(small).encode())
    forged = TAG + base64.b64encode(client._private_key.sign(envelope)).decode()
    downgrade = verify_bundle(_bundle(small, forged), key_set)
    assert downgrade.status is VerificationStatus.MISMATCH
    assert run(_bundle(small, forged)) == verify_cli.EXIT_INVALID


def test_edge_client_verifies_envelope_signed_permit():
    private_key = Ed25519PrivateKey.generate()
    permit: dict[str, Any] = {
        "permit_id": "permit-1",
        "issuer_wallet_id": "w-issuer",
        "subject_wallet_id": "w-subject",
        "scopes": ["billing:charge"],
        "allowed_tools": [f"tool-{i:04d}-{'x' * 40}" for i in range(120)],
        "max_credits": "10",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "nonce": "n1",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "key_id": KID,
    }
    payload = LocalPermitValidator.permit_signing_payload(permit)
    signing_bytes = sdk.canonical_json(payload).encode()
    assert len(signing_bytes) > KMS_MAX_RAW_MESSAGE_BYTES
    envelope = sdk.signature_message(SIGNATURE_ENVELOPE_ALG, KID, signing_bytes)
    assert envelope is not None
    permit["signature"] = TAG + base64.b64encode(private_key.sign(envelope)).decode()
    validator = LocalPermitValidator(permit, {KID: _raw_public(private_key)})

    assert validator.verify_permit() is True
    assert validator.verify_permit(dict(permit, max_credits="1000")) is False
    bad_tag = dict(permit, signature="Ed25519-v9:" + permit["signature"][len(TAG) :])
    assert validator.verify_permit(bad_tag) is False
