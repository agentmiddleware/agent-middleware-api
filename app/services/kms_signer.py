"""Optional AWS KMS Ed25519 signer for receipts, permits, and audit events.

Opt-in with ``TRUST_SIGNING_BACKEND=aws_kms``; the environment-seed signer
stays the default. The KMS key must be ``KeySpec=ECC_NIST_EDWARDS25519`` with
``KeyUsage=SIGN_VERIFY``.

Every call uses ``SigningAlgorithm=ED25519_SHA_512`` with
``MessageType=RAW``: pure Ed25519 (RFC 8032) over exactly the canonical bytes
the environment signer signs, so ``b2a-verify-receipt`` and every other
existing verifier accept the result unchanged. Two look-alikes are refused on
purpose:

* ``MessageType=DIGEST`` is Ed25519ph (pre-hashed), a different signature
  scheme that a plain Ed25519 verifier rejects.
* ECDSA key specs produce DER signatures no verifier here understands.

KMS caps a RAW message at 4096 bytes. ``SigningKeyService`` never sends a
larger one: a canonical payload over the cap is signed through the bounded
``Ed25519-sha256-envelope`` (see ``signing_keys``), still pure Ed25519 over RAW
bytes. This signer keeps its own guard, so an oversized message from any other
caller fails closed with ``kms_message_too_large`` instead of silently
switching to DIGEST.

``boto3`` is imported lazily and is not in ``requirements.txt``: only an image
that opts in needs it.
"""

from __future__ import annotations

from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

KMS_SIGNING_ALGORITHM = "ED25519_SHA_512"
KMS_MESSAGE_TYPE = "RAW"
KMS_KEY_SPEC = "ECC_NIST_EDWARDS25519"
KMS_MAX_RAW_MESSAGE_BYTES = 4096
ED25519_SIGNATURE_BYTES = 64


def _signing_key_error(code: str) -> Exception:
    # Imported here: signing_keys imports this module lazily, and the shared
    # error type keeps startup/health error codes in one family.
    from .signing_keys import SigningKeyError

    return SigningKeyError(code)


def build_kms_client(region: str | None = None) -> Any:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise _signing_key_error("kms_boto3_unavailable") from exc
    return boto3.client("kms", region_name=region or None)


class KmsEd25519Signer:
    """Duck-types the two ``Ed25519PrivateKey`` methods the signer uses.

    ``public_key()`` is fetched once from KMS and cached; ``sign()`` makes one
    KMS Sign call and verifies the returned signature locally against that
    public key before handing it back, so a wrong key, algorithm, or message
    type fails here rather than in a third party's verifier.
    """

    def __init__(
        self,
        key_id: str,
        *,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not key_id.strip():
            raise _signing_key_error("trust_signing_kms_key_required")
        self._key_id = key_id.strip()
        self._region = region
        self._client_instance = client
        self._public_key: Ed25519PublicKey | None = None

    def _client(self) -> Any:
        if self._client_instance is None:
            self._client_instance = build_kms_client(self._region)
        return self._client_instance

    def public_key(self) -> Ed25519PublicKey:
        if self._public_key is not None:
            return self._public_key
        client = self._client()
        try:
            response = client.get_public_key(KeyId=self._key_id)
        except Exception as exc:
            raise _signing_key_error("kms_get_public_key_failed") from exc
        key_spec = response.get("KeySpec")
        if key_spec is not None and key_spec != KMS_KEY_SPEC:
            raise _signing_key_error("kms_key_not_ed25519")
        if response.get("KeyUsage", "SIGN_VERIFY") != "SIGN_VERIFY":
            raise _signing_key_error("kms_key_not_sign_verify")
        algorithms = response.get("SigningAlgorithms")
        if algorithms is not None and KMS_SIGNING_ALGORITHM not in algorithms:
            raise _signing_key_error("kms_key_lacks_ed25519_sha_512")
        try:
            public_key = load_der_public_key(response["PublicKey"])
        except (KeyError, ValueError, TypeError) as exc:
            raise _signing_key_error("kms_public_key_invalid") from exc
        if not isinstance(public_key, Ed25519PublicKey):
            raise _signing_key_error("kms_key_not_ed25519")
        self._public_key = public_key
        return public_key

    def sign(self, data: bytes) -> bytes:
        if len(data) > KMS_MAX_RAW_MESSAGE_BYTES:
            raise _signing_key_error("kms_message_too_large")
        public_key = self.public_key()
        client = self._client()
        try:
            response = client.sign(
                KeyId=self._key_id,
                Message=data,
                MessageType=KMS_MESSAGE_TYPE,
                SigningAlgorithm=KMS_SIGNING_ALGORITHM,
            )
        except Exception as exc:
            raise _signing_key_error("kms_sign_failed") from exc
        algorithm = response.get("SigningAlgorithm", KMS_SIGNING_ALGORITHM)
        signature = response.get("Signature")
        if (
            algorithm != KMS_SIGNING_ALGORITHM
            or not isinstance(signature, (bytes, bytearray))
            or len(signature) != ED25519_SIGNATURE_BYTES
        ):
            raise _signing_key_error("kms_signature_invalid")
        try:
            public_key.verify(bytes(signature), data)
        except InvalidSignature as exc:
            raise _signing_key_error("kms_signature_invalid") from exc
        return bytes(signature)
