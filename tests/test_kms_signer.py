"""AWS KMS Ed25519 signing produces receipts the existing verifier accepts.

KMS is mocked by a client backed by a local Ed25519 key that answers only the
exact request shape real KMS needs for pure Ed25519
(``SigningAlgorithm=ED25519_SHA_512``, ``MessageType=RAW``). The end-to-end
test runs one real governed invoke with that signer installed, then verifies
the exported receipt through :mod:`b2a_sdk.receipt_verifier` and the
``b2a-verify-receipt`` CLI entry point, neither of which knows KMS exists.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.core.config import Settings
from app.core.trust_mode import TrustModeGuardrailError, validate_trust_mode_config
from app.main import app
from app.services import signing_keys as signing_keys_module
from app.services.kms_signer import (
    KMS_MAX_RAW_MESSAGE_BYTES,
    KMS_MESSAGE_TYPE,
    KMS_SIGNING_ALGORITHM,
    KmsEd25519Signer,
)
from app.services.signing_keys import (
    SigningKeyError,
    canonical_json,
    get_signing_key_service,
    validate_signing_key_configuration,
)
from b2a_sdk import verify_cli
from b2a_sdk.receipt_verifier import (
    VerificationStatus,
    key_set_from_document,
    verify_bundle,
)
from tests.test_receipt_portability import (
    _invoke_governed_tool,
    _portable_bundle_and_keys,
)
from tests.test_trust_helpers import provision_agent_wallet


class FakeKmsClient:
    """The subset of the boto3 KMS client the signer calls, on a local key."""

    def __init__(self, private_key: Any | None = None, **overrides: Any) -> None:
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._overrides = overrides
        self.sign_calls: list[dict[str, Any]] = []
        self.public_key_calls = 0

    def get_public_key(self, *, KeyId: str) -> dict[str, Any]:  # noqa: N803
        self.public_key_calls += 1
        response = {
            "KeyId": KeyId,
            "PublicKey": self._private_key.public_key().public_bytes(
                Encoding.DER, PublicFormat.SubjectPublicKeyInfo
            ),
            "KeySpec": "ECC_NIST_EDWARDS25519",
            "KeyUsage": "SIGN_VERIFY",
            "SigningAlgorithms": ["ED25519_SHA_512", "ED25519_PH_SHA_512"],
        }
        response.update(self._overrides)
        return response

    def sign(
        self,
        *,
        KeyId: str,  # noqa: N803
        Message: bytes,  # noqa: N803
        MessageType: str,  # noqa: N803
        SigningAlgorithm: str,  # noqa: N803
    ) -> dict[str, Any]:
        self.sign_calls.append(
            {
                "KeyId": KeyId,
                "Message": Message,
                "MessageType": MessageType,
                "SigningAlgorithm": SigningAlgorithm,
            }
        )
        # Real KMS would compute Ed25519ph for DIGEST, which a plain Ed25519
        # verifier rejects; refusing here makes a regression loud.
        if MessageType != "RAW" or SigningAlgorithm != "ED25519_SHA_512":
            raise AssertionError(
                f"unexpected KMS request {MessageType}/{SigningAlgorithm}"
            )
        return {
            "KeyId": KeyId,
            "Signature": self._private_key.sign(Message),
            "SigningAlgorithm": SigningAlgorithm,
        }


def test_kms_signer_signs_raw_ed25519_over_exact_bytes():
    local_key = Ed25519PrivateKey.generate()
    client = FakeKmsClient(local_key)
    signer = KmsEd25519Signer("alias/trust", client=client)

    message = canonical_json({"receipt_id": "r1", "credits": "2"}).encode()
    signature = signer.sign(message)

    assert KMS_SIGNING_ALGORITHM == "ED25519_SHA_512"
    assert KMS_MESSAGE_TYPE == "RAW"
    assert client.sign_calls == [
        {
            "KeyId": "alias/trust",
            "Message": message,
            "MessageType": "RAW",
            "SigningAlgorithm": "ED25519_SHA_512",
        }
    ]
    # Byte-identical to what the environment signer would produce: Ed25519 is
    # deterministic, so the same key over the same bytes gives one signature.
    assert signature == local_key.sign(message)
    local_key.public_key().verify(signature, message)
    # The public key is fetched once and cached.
    signer.sign(message)
    assert client.public_key_calls == 1


def test_kms_signer_rejects_non_ed25519_key():
    ecdsa_key = generate_private_key(SECP256R1())
    client = FakeKmsClient(ecdsa_key, KeySpec="ECC_NIST_P256")
    with pytest.raises(SigningKeyError, match="kms_key_not_ed25519"):
        KmsEd25519Signer("k", client=client).public_key()

    # Even if KMS omitted KeySpec, the DER key itself must be Ed25519.
    client = FakeKmsClient(ecdsa_key, KeySpec=None)
    with pytest.raises(SigningKeyError, match="kms_key_not_ed25519"):
        KmsEd25519Signer("k", client=client).public_key()


def test_kms_signer_rejects_key_without_pure_ed25519_algorithm():
    client = FakeKmsClient(SigningAlgorithms=["ED25519_PH_SHA_512"])
    with pytest.raises(SigningKeyError, match="kms_key_lacks_ed25519_sha_512"):
        KmsEd25519Signer("k", client=client).public_key()


def test_kms_signer_rejects_signature_from_a_different_key():
    published = Ed25519PrivateKey.generate()
    client = FakeKmsClient(published)
    signer = KmsEd25519Signer("k", client=client)
    signer.public_key()
    # KMS now answers with a different key than the one it published.
    client._private_key = Ed25519PrivateKey.generate()
    with pytest.raises(SigningKeyError, match="kms_signature_invalid"):
        signer.sign(b"payload")


def test_kms_signer_refuses_oversized_message_instead_of_digest_mode():
    client = FakeKmsClient()
    signer = KmsEd25519Signer("k", client=client)
    with pytest.raises(SigningKeyError, match="kms_message_too_large"):
        signer.sign(b"x" * (KMS_MAX_RAW_MESSAGE_BYTES + 1))
    assert client.sign_calls == []


def test_kms_signer_wraps_client_errors_with_stable_code():
    class Broken(FakeKmsClient):
        def sign(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("AccessDeniedException: secret detail")

    signer = KmsEd25519Signer("k", client=Broken())
    with pytest.raises(SigningKeyError, match="^kms_sign_failed$"):
        signer.sign(b"payload")


def test_kms_signer_requires_key_id():
    with pytest.raises(SigningKeyError, match="trust_signing_kms_key_id_required"):
        KmsEd25519Signer("  ")


def test_kms_backend_configuration_validation(monkeypatch):
    settings = Settings(
        TRUST_SIGNING_BACKEND="aws_kms",
        TRUST_SIGNING_KMS_KEY_ID="",
        TRUST_SIGNING_PRIVATE_KEY_B64="",
        TRUST_MODE_ENABLED=True,
    )
    with pytest.raises(SigningKeyError, match="trust_signing_kms_key_id_required"):
        validate_signing_key_configuration(settings)

    settings = Settings(
        TRUST_SIGNING_BACKEND="aws_kms",
        TRUST_SIGNING_KMS_KEY_ID="alias/trust",
        TRUST_MODE_ENABLED=True,
    )
    # boto3 is optional and absent from requirements.txt: a missing package is
    # a stable configuration error, found without any network call.
    monkeypatch.setattr(
        signing_keys_module.importlib.util, "find_spec", lambda name: None
    )
    with pytest.raises(SigningKeyError, match="kms_boto3_unavailable"):
        validate_signing_key_configuration(settings)

    monkeypatch.setattr(
        signing_keys_module.importlib.util, "find_spec", lambda name: object()
    )
    assert validate_signing_key_configuration(settings) == "aws_kms"


def test_signing_backend_setting_rejects_unknown_values():
    with pytest.raises(ValueError, match="TRUST_SIGNING_BACKEND must be"):
        Settings(TRUST_SIGNING_BACKEND="aws_kms_ecdsa")
    assert Settings().TRUST_SIGNING_BACKEND == "env"


def _production_config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = dict(
        environment="production",
        trust_mode_enabled=True,
        signing_private_key_b64="",
        allow_legacy_unpermitted_mcp=False,
        enable_proof_surfaces=False,
        database_url="postgresql+asyncpg://u:p@db.internal/app",
        redis_url="redis://cache.internal:6379/0",
    )
    config.update(overrides)
    return config


def test_production_guardrail_accepts_kms_in_place_of_env_seed():
    validate_trust_mode_config(
        **_production_config(
            signing_backend="aws_kms", signing_kms_key_id="alias/trust"
        )
    )
    with pytest.raises(TrustModeGuardrailError, match="TRUST_SIGNING_KMS_KEY_ID"):
        validate_trust_mode_config(**_production_config(signing_backend="aws_kms"))
    # The default backend still requires the seed.
    with pytest.raises(
        TrustModeGuardrailError, match="TRUST_SIGNING_PRIVATE_KEY_B64 is required"
    ):
        validate_trust_mode_config(**_production_config())


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def kms_signing(monkeypatch):
    """Install a KMS signer (mocked) on the process signing service."""
    service = get_signing_key_service()
    client = FakeKmsClient()
    monkeypatch.setattr(
        service, "_private_key", KmsEd25519Signer("alias/trust", client=client)
    )
    monkeypatch.setattr(service, "_key_id", "kms-ed25519-test")
    return client


@pytest.mark.anyio
async def test_kms_signed_receipt_verifies_with_existing_verifier(
    client, clean_database, kms_signing, tmp_path
):
    provisioned = await provision_agent_wallet(client)
    _permit, receipt = await _invoke_governed_tool(
        client, provisioned, tool_name="kms-echo"
    )
    bundle, keys = await _portable_bundle_and_keys(
        client, provisioned, receipt["receipt_id"]
    )

    assert bundle["kid"] == "kms-ed25519-test"
    # Every signature on the path came from KMS, and every KMS call was pure
    # Ed25519 over raw bytes.
    assert kms_signing.sign_calls
    assert {c["MessageType"] for c in kms_signing.sign_calls} == {"RAW"}
    assert {c["SigningAlgorithm"] for c in kms_signing.sign_calls} == {
        "ED25519_SHA_512"
    }
    # The receipt's signing input is among the exact messages KMS signed.
    signed_messages = {c["Message"] for c in kms_signing.sign_calls}
    assert bundle["signing_input"].encode() in signed_messages

    result = verify_bundle(bundle, key_set_from_document(keys))
    assert result.status is VerificationStatus.VERIFIED, result.reason
    assert result.key_id == "kms-ed25519-test"

    bundle_path = tmp_path / "receipt.json"
    keys_path = tmp_path / "trust-keys.json"
    bundle_path.write_text(json.dumps(bundle))
    keys_path.write_text(json.dumps(keys))
    assert (
        verify_cli.main(["--bundle", str(bundle_path), "--keys", str(keys_path)])
        == verify_cli.EXIT_VERIFIED
    )
