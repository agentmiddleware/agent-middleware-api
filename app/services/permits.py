"""
Signed Capability Permits
=========================
A permit is a compact, signed, expiring token that grants an agent scoped
authority to invoke specific tools on behalf of a wallet, up to a spend cap.

Format (JWT-like, but with a fixed algorithm — no alg negotiation):

    base64url(payload_json) + "." + base64url(signature)

Claims:
    jti        unique permit id (also the replay nonce for single-use permits)
    wallet_id  the wallet the permit acts for
    scope      allowed tool names / service ids ("*" = any)
    max_spend  optional credit ceiling (string Decimal), enforced where the
               per-call cost is known
    agent_id   optional agent the permit was issued to
    iat / exp  issued-at / expiry (unix seconds)
    single_use if true, the jti is claimed once via the durable nonce store so
               the permit cannot be replayed

The server verifies permits; with the Ed25519 public key an agent can also
verify a permit it holds before presenting it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from functools import lru_cache
from typing import Any, Iterable

from ..core.config import get_settings

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    _ED25519_AVAILABLE = True
except Exception:  # pragma: no cover - only when cryptography is missing
    _ED25519_AVAILABLE = False


class PermitError(Exception):
    """Raised when a permit is malformed, invalid, expired, or unauthorized."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


class PermitService:
    """Issues and verifies signed capability permits."""

    def __init__(self, signing_key_b64: str = "", hmac_secret: str = ""):
        self._ed_private: Any = None
        self._ed_public: Any = None
        self._hmac_secret: bytes = b""

        if _ED25519_AVAILABLE:
            self.algorithm = "ed25519"
            if signing_key_b64:
                self._ed_private = Ed25519PrivateKey.from_private_bytes(
                    base64.b64decode(signing_key_b64)
                )
            else:
                self._ed_private = Ed25519PrivateKey.generate()
            self._ed_public = self._ed_private.public_key()
        else:
            self.algorithm = "hmac-sha256"
            secret = hmac_secret or base64.b64encode(os.urandom(32)).decode()
            self._hmac_secret = secret.encode()

    def _sign(self, payload: bytes) -> bytes:
        if self.algorithm == "ed25519":
            return self._ed_private.sign(payload)
        return hmac.new(self._hmac_secret, payload, hashlib.sha256).digest()

    def _verify_sig(self, payload: bytes, sig: bytes) -> bool:
        if self.algorithm == "ed25519":
            try:
                self._ed_public.verify(sig, payload)
                return True
            except InvalidSignature:
                return False
            except Exception:
                return False
        expected = hmac.new(self._hmac_secret, payload, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)

    def public_key_b64(self) -> str | None:
        if self.algorithm == "ed25519" and self._ed_public is not None:
            raw = self._ed_public.public_bytes(Encoding.Raw, PublicFormat.Raw)
            return base64.b64encode(raw).decode()
        return None

    def issue(
        self,
        *,
        wallet_id: str,
        scope: Iterable[str],
        max_spend: Any = None,
        ttl_seconds: int | None = None,
        agent_id: str | None = None,
        single_use: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        now = int(time.time())
        ttl = int(ttl_seconds or settings.PERMIT_DEFAULT_TTL_SECONDS)
        claims = {
            "jti": _b64url_encode(os.urandom(12)),
            "wallet_id": wallet_id,
            "scope": list(scope),
            "max_spend": (str(max_spend) if max_spend is not None else None),
            "agent_id": agent_id,
            "iat": now,
            "exp": now + max(1, ttl),
            "single_use": bool(single_use),
            "alg": self.algorithm,
        }
        payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
        token = f"{_b64url_encode(payload)}.{_b64url_encode(self._sign(payload))}"
        return {"permit": token, "claims": claims}

    def decode(self, token: str) -> dict[str, Any]:
        """Verify signature and expiry, returning the claims. Raises PermitError."""
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            payload = _b64url_decode(payload_b64)
            sig = _b64url_decode(sig_b64)
        except Exception:
            raise PermitError("malformed_permit")

        if not self._verify_sig(payload, sig):
            raise PermitError("invalid_signature")

        try:
            claims: dict[str, Any] = json.loads(payload)
        except Exception:
            raise PermitError("malformed_permit")

        if int(claims.get("exp", 0)) < int(time.time()):
            raise PermitError("expired")
        return claims


async def require_permit_for_tool(
    token: str | None,
    *,
    wallet_id: str,
    tool_name: str,
) -> dict[str, Any]:
    """Authorize a tool call against a permit. Raises PermitError on failure.

    For single-use permits the jti is claimed once via the durable nonce store,
    so a captured permit cannot be replayed.
    """
    if not token:
        raise PermitError("permit_required")

    service = get_permit_service()
    claims = service.decode(token)

    if claims.get("wallet_id") != wallet_id:
        raise PermitError("wallet_mismatch")

    scope = claims.get("scope") or []
    if "*" not in scope and tool_name not in scope:
        raise PermitError("out_of_scope")

    if claims.get("single_use"):
        from ..core.durable_state import get_durable_state

        ttl = max(1, int(claims.get("exp", 0)) - int(time.time()))
        claimed = await get_durable_state().claim_once(
            f"permit:{claims.get('jti')}", ttl
        )
        if not claimed:
            raise PermitError("permit_replayed")

    return claims


@lru_cache()
def get_permit_service() -> PermitService:
    settings = get_settings()
    return PermitService(settings.PERMIT_SIGNING_KEY, settings.PERMIT_HMAC_SECRET)
