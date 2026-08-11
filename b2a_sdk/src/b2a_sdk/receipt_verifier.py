"""Offline verification of trust-plane receipts.

A receipt is only evidence if someone who does not trust the issuer can check
it. Everything in this module therefore runs with no network, no database, and
no credential: it takes a portable receipt bundle plus a published key set and
answers whether the signature holds.

Two rules keep that answer meaningful:

1. Every field this module reports is read out of the *signed bytes*. Nothing
   is taken from the enclosing bundle, which is unauthenticated envelope data.
   A bundle claiming ``receipt_id: X`` around a payload for ``Y`` is rejected.
2. Failure is never silently "false". An unreachable key set, an unknown key,
   and a bad signature are different situations, and a caller that cannot tell
   them apart will eventually read an outage as fraud. See
   :class:`VerificationStatus`.

Typical use::

    from b2a_sdk.receipt_verifier import verify_bundle

    result = verify_bundle(bundle, key_set)
    if result.ok:
        print(result.claims["tool"], result.claims["credits_charged"])

The only dependency beyond the standard library is ``cryptography``, installed
via the ``verify`` extra::

    pip install "b2a-sdk[verify]"
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "CANONICALIZATION",
    "VerificationError",
    "VerificationResult",
    "VerificationStatus",
    "canonical_json",
    "key_set_from_document",
    "verify_bundle",
]

# The canonicalization contract these rules implement. A bundle declaring a
# different version is refused rather than verified under rules it was not
# signed with.
CANONICALIZATION = "awi-canonical-json/1"

_ED25519_RAW_LEN = 32


class VerificationStatus(str, Enum):
    """Why verification concluded what it did.

    ``VERIFIED`` and ``INVALID`` are claims about the receipt. Everything else
    is a claim about the *verifier's* situation — missing input, unknown key,
    unreadable bundle — and must not be reported as evidence of tampering.
    """

    VERIFIED = "verified"
    INVALID = "invalid"
    MALFORMED = "malformed"
    UNKNOWN_KEY = "unknown_key"
    KEY_REVOKED = "key_revoked"
    UNSUPPORTED = "unsupported"


class VerificationError(Exception):
    """Raised only for programming errors, never for a failed verification."""


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of checking one receipt bundle."""

    status: VerificationStatus
    reason: str | None = None
    receipt_id: str | None = None
    key_id: str | None = None
    #: Fields parsed out of the signed bytes. Populated only when ``ok``.
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True only when the signature verified over the signed bytes."""
        return self.status is VerificationStatus.VERIFIED

    @property
    def is_tampered(self) -> bool:
        """True only for a bundle that is well-formed but does not verify.

        Distinct from :attr:`ok` being False, which also covers "cannot tell".
        """
        return self.status is VerificationStatus.INVALID


def canonical_json(payload: Any) -> str:
    """Serialize already-decoded JSON the way the trust plane signs it.

    The rules are: keys sorted at every level, no insignificant whitespace,
    and non-ASCII escaped. Numbers and timestamps are already strings by the
    time they reach a signed payload, so no numeric formatting rules are
    needed here — which is what makes this reimplementable in any language.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _b64decode(value: str, *, urlsafe: bool = False) -> bytes | None:
    """Strict base64 decode that returns None instead of raising."""
    if not isinstance(value, str):
        return None
    try:
        if urlsafe:
            # JWK members omit padding; restore it before decoding.
            padded = value + "=" * (-len(value) % 4)
            return base64.urlsafe_b64decode(padded)
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def key_set_from_document(document: Any) -> dict[str, bytes]:
    """Extract usable Ed25519 public keys from a ``trust-keys.json`` document.

    Accepts either the ``public_key_b64`` form or the JWK mirror. Keys the
    issuing plane marks ``disabled`` are dropped, matching the plane's own
    refusal to verify against them — a revoked key must not keep validating
    receipts just because a cached copy of the document still lists it.
    """
    if not isinstance(document, dict):
        raise VerificationError("key set document must be a JSON object")

    entries = document.get("keys")
    if not isinstance(entries, list):
        raise VerificationError("key set document has no 'keys' list")

    keys: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid") or entry.get("key_id")
        if not isinstance(kid, str) or not kid:
            continue
        if entry.get("status") == "disabled":
            continue
        if entry.get("alg") not in (None, "Ed25519"):
            continue

        # Fall through to the JWK mirror whenever the raw form is absent,
        # unreadable, or the wrong length — an empty string decodes cleanly to
        # zero bytes, so "decoded without error" is not enough to accept it.
        raw = _b64decode(entry.get("public_key_b64", ""))
        if raw is None or len(raw) != _ED25519_RAW_LEN:
            jwk = entry.get("jwk")
            if isinstance(jwk, dict) and jwk.get("crv") == "Ed25519":
                raw = _b64decode(jwk.get("x", ""), urlsafe=True)
        if raw is None or len(raw) != _ED25519_RAW_LEN:
            continue
        keys[kid] = raw
    return keys


def _load_verifier(raw_public_key: bytes):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise VerificationError(
            "Ed25519 verification requires the 'cryptography' package. "
            'Install it with: pip install "b2a-sdk[verify]"'
        ) from exc
    return Ed25519PublicKey.from_public_bytes(raw_public_key)


def _fail(
    status: VerificationStatus,
    reason: str,
    *,
    receipt_id: str | None = None,
    key_id: str | None = None,
) -> VerificationResult:
    return VerificationResult(
        status=status,
        reason=reason,
        receipt_id=receipt_id,
        key_id=key_id,
    )


def verify_bundle(
    bundle: Any,
    key_set: dict[str, bytes],
    *,
    expected_issuer: str | None = None,
) -> VerificationResult:
    """Verify a portable receipt bundle against published public keys.

    Args:
        bundle: The object returned by ``GET /v1/receipts/{id}/portable``,
            either as a dict or a JSON string.
        key_set: Mapping of key id to raw 32-byte Ed25519 public key, as
            produced by :func:`key_set_from_document`.
        expected_issuer: When given, the bundle's ``issuer`` must match. Use
            this when you know which plane the receipt should have come from;
            without it, a valid receipt from *some other* plane still verifies.

    Returns:
        A :class:`VerificationResult`. Inspect ``status`` rather than only
        ``ok`` when the difference between "invalid" and "cannot tell"
        matters.
    """
    if isinstance(bundle, (str, bytes)):
        try:
            bundle = json.loads(bundle)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _fail(VerificationStatus.MALFORMED, "bundle is not valid JSON")
    if not isinstance(bundle, dict):
        return _fail(VerificationStatus.MALFORMED, "bundle must be a JSON object")

    signing_input = bundle.get("signing_input")
    signature_b64 = bundle.get("signature")
    key_id = bundle.get("kid")
    if not isinstance(signing_input, str) or not signing_input:
        return _fail(VerificationStatus.MALFORMED, "bundle has no signing_input")
    if not isinstance(signature_b64, str) or not signature_b64:
        return _fail(VerificationStatus.MALFORMED, "bundle has no signature")
    if not isinstance(key_id, str) or not key_id:
        return _fail(VerificationStatus.MALFORMED, "bundle has no kid")

    algorithm = bundle.get("alg", "Ed25519")
    if algorithm != "Ed25519":
        return _fail(
            VerificationStatus.UNSUPPORTED,
            f"unsupported signature algorithm: {algorithm!r}",
            key_id=key_id,
        )

    declared = bundle.get("canonicalization", CANONICALIZATION)
    if declared != CANONICALIZATION:
        # Verifying under rules the payload was not signed with would produce a
        # confident answer to the wrong question.
        return _fail(
            VerificationStatus.UNSUPPORTED,
            f"unsupported canonicalization: {declared!r} (this verifier "
            f"implements {CANONICALIZATION!r})",
            key_id=key_id,
        )

    if expected_issuer is not None and bundle.get("issuer") != expected_issuer:
        return _fail(
            VerificationStatus.INVALID,
            f"issuer mismatch: bundle claims {bundle.get('issuer')!r}",
            key_id=key_id,
        )

    # Parse the signed bytes before checking the signature so a malformed
    # payload is reported as malformed rather than as a forgery.
    try:
        payload = json.loads(signing_input)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _fail(
            VerificationStatus.MALFORMED,
            "signing_input is not valid JSON",
            key_id=key_id,
        )
    if not isinstance(payload, dict):
        return _fail(
            VerificationStatus.MALFORMED,
            "signing_input is not a JSON object",
            key_id=key_id,
        )

    signature = _b64decode(signature_b64)
    if signature is None:
        return _fail(
            VerificationStatus.MALFORMED,
            "signature is not valid base64",
            key_id=key_id,
        )

    raw_public_key = key_set.get(key_id)
    if raw_public_key is None:
        # Not a verdict on the receipt: this verifier simply does not hold the
        # key. Refresh the key set from the issuer before drawing conclusions.
        return _fail(
            VerificationStatus.UNKNOWN_KEY,
            f"no published key for kid {key_id!r}",
            key_id=key_id,
        )
    if len(raw_public_key) != _ED25519_RAW_LEN:
        return _fail(
            VerificationStatus.MALFORMED,
            f"public key for kid {key_id!r} is not a 32-byte Ed25519 key",
            key_id=key_id,
        )

    # The signature covers signing_input verbatim. Re-serializing the parsed
    # object here would silently "fix" a payload whose bytes were altered in a
    # way that survives a JSON round trip, so the original string is used.
    try:
        _load_verifier(raw_public_key).verify(
            signature, signing_input.encode("utf-8")
        )
    except VerificationError:
        raise
    except Exception:
        # cryptography raises InvalidSignature; anything else here is also a
        # failure to verify, and must not escape as a crash.
        return _fail(
            VerificationStatus.INVALID,
            "signature does not verify over signing_input",
            key_id=key_id,
        )

    # The signature holds. Remaining checks are internal consistency of the
    # signed payload itself.
    if payload.get("kid") != key_id:
        return _fail(
            VerificationStatus.INVALID,
            "signed payload names a different kid than the bundle",
            key_id=key_id,
        )

    stated_hash = payload.get("payload_hash")
    if isinstance(stated_hash, str):
        inner = {k: v for k, v in payload.items() if k != "payload_hash"}
        computed = hashlib.sha256(canonical_json(inner).encode("utf-8")).hexdigest()
        if computed != stated_hash:
            return _fail(
                VerificationStatus.INVALID,
                "payload_hash does not match the signed payload",
                key_id=key_id,
            )

    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        return _fail(
            VerificationStatus.MALFORMED,
            "signed payload has no receipt_id",
            key_id=key_id,
        )

    # Envelope fields are unauthenticated. If the bundle advertises a receipt
    # id other than the signed one, whoever presented it is describing the
    # evidence incorrectly — refuse rather than quietly trusting the signed
    # value and letting the mismatch pass unnoticed.
    envelope_receipt_id = bundle.get("receipt_id")
    if envelope_receipt_id is not None and envelope_receipt_id != receipt_id:
        return _fail(
            VerificationStatus.INVALID,
            "bundle receipt_id does not match the signed receipt_id",
            receipt_id=receipt_id,
            key_id=key_id,
        )

    return VerificationResult(
        status=VerificationStatus.VERIFIED,
        receipt_id=receipt_id,
        key_id=key_id,
        claims=payload,
    )
