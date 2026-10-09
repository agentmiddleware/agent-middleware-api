"""JWT access token creation and verification.

Login tokens use Ed25519, but not the trust-plane key that signs permits
and receipts. The login key is derived from that seed, so a receipt or
permit signature cannot pass as a login token. The key id travels in the
protected header. Verification requires the login domain label.

Short-lived: 15 min access, 7 day refresh.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.core.config import get_settings
from app.services.signing_keys import _decode_private_key


JWT_ALGORITHM = "EdDSA"
JWT_ISSUER = "agent-middleware-api"
JWT_AUDIENCE = "agent-middleware-api"
# Protected header type. Receipts and permits are not login tokens.
JWT_TYPE = "amw-login+jwt"
# Payload claim that verification requires. Access vs refresh stays in `type`.
JWT_DOMAIN = "login"
# HKDF info. This is what makes the login seed a different key.
JWT_SIGNING_INFO = b"agent-middleware-api/login-token/v1"
JWT_ACCESS_EXPIRY = 900  # 15 minutes
JWT_REFRESH_EXPIRY = 604800  # 7 days


def _derive_login_key(trust_key: Ed25519PrivateKey) -> Ed25519PrivateKey:
    """Derive the login-token key from the trust-plane seed.

    Same configured secret, different key. A signature over a receipt or
    permit does not verify as a login token.
    """
    seed = trust_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=JWT_SIGNING_INFO,
    ).derive(seed)
    return Ed25519PrivateKey.from_private_bytes(derived)


@dataclass(frozen=True)
class JWTPayload:
    sub: str  # wallet_id
    key_id: str | None
    scopes: list[str]
    # Epoch seconds, as PyJWT decodes them. Callers that need a datetime
    # convert explicitly (see app.routers.auth._exp_to_datetime).
    iat: int
    exp: int
    iss: str
    aud: str
    jti: str  # unique token id
    type: str  # access | refresh


class JWTError(Exception):
    pass


class JWTService:
    """Create and verify JWT access tokens signed with Ed25519."""

    def _load_keys(self) -> tuple[Ed25519PrivateKey, str]:
        """Load the login signing key and return (key, key_id).

        The key id is the fingerprint of the login public key, not the
        trust-plane key id published for receipts.
        """
        settings = get_settings()
        b64_key = settings.TRUST_SIGNING_PRIVATE_KEY_B64
        if not b64_key:
            raise JWTError("signing_key_not_configured")

        private_key = _derive_login_key(_decode_private_key(b64_key))
        raw_public = private_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )
        key_id = "ed25519-" + hashlib.sha256(raw_public).hexdigest()[:16]
        return private_key, key_id

    def _encode(self, payload: dict) -> str:
        """Sign a login token.

        The key id is in the protected header. The domain label is a payload
        claim, which verification requires.
        """
        private_key, signing_key_id = self._load_keys()
        body = dict(payload)
        body["dom"] = JWT_DOMAIN
        return jwt.encode(
            body,
            private_key,
            algorithm=JWT_ALGORITHM,
            headers={"kid": signing_key_id, "typ": JWT_TYPE},
        )

    def create_access_token(
        self,
        wallet_id: str,
        key_id: str | None,
        scopes: list[str],
    ) -> str:
        """Create a short-lived access token."""
        now = datetime.now(timezone.utc)
        jti = f"jwt-{uuid.uuid4().hex[:16]}"

        return self._encode(
            {
                "sub": wallet_id,
                "key_id": key_id,
                "scopes": scopes,
                "iat": now,
                "exp": now + timedelta(seconds=JWT_ACCESS_EXPIRY),
                "iss": JWT_ISSUER,
                "aud": JWT_AUDIENCE,
                "jti": jti,
                "type": "access",
            }
        )

    def create_refresh_token(
        self, wallet_id: str, scopes: list[str] | None = None
    ) -> str:
        """Create a long-lived refresh token."""
        now = datetime.now(timezone.utc)
        jti = f"jwt-refresh-{uuid.uuid4().hex[:16]}"

        return self._encode(
            {
                "sub": wallet_id,
                "iat": now,
                "exp": now + timedelta(seconds=JWT_REFRESH_EXPIRY),
                "iss": JWT_ISSUER,
                "aud": JWT_AUDIENCE,
                "jti": jti,
                "type": "refresh",
                "scopes": scopes if scopes is not None else [],
            }
        )

    def verify_token(self, token: str, token_type: str = "access") -> JWTPayload:
        """Verify a JWT and return its payload."""
        private_key, signing_key_id = self._load_keys()

        try:
            payload = jwt.decode(
                token,
                private_key.public_key(),
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                # PyJWT checks exp only when it is present, so a signed token
                # without one would never expire; the rest are read below and
                # would otherwise surface as a KeyError, not a refused token.
                # Every token this service mints carries all of them.
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
            )
            header = jwt.get_unverified_header(token)
        except jwt.ExpiredSignatureError:
            raise JWTError("token_expired")
        except jwt.InvalidTokenError as e:
            raise JWTError(f"invalid_token: {e}")

        # Header is signed, so this check binds the token to the login key
        # rather than to whatever key id a caller writes in the body.
        if header.get("kid") != signing_key_id:
            raise JWTError("signing_key_mismatch")
        if header.get("typ") != JWT_TYPE or payload.get("dom") != JWT_DOMAIN:
            raise JWTError("token_domain_mismatch")

        if payload.get("type") != token_type:
            raise JWTError(f"token_type_mismatch: expected {token_type}")

        scopes = payload.get("scopes")
        if not isinstance(scopes, list) or not all(
            isinstance(scope, str) for scope in scopes
        ):
            raise JWTError("invalid_or_missing_scopes")

        return JWTPayload(
            sub=payload["sub"],
            key_id=payload.get("key_id"),
            scopes=scopes,
            iat=payload["iat"],
            exp=payload["exp"],
            iss=payload["iss"],
            aud=payload["aud"],
            jti=payload["jti"],
            type=payload["type"],
        )

    def verify_access_token(self, token: str) -> JWTPayload:
        return self.verify_token(token, token_type="access")

    def verify_refresh_token(self, token: str) -> JWTPayload:
        return self.verify_token(token, token_type="refresh")


# Module-level singleton
_jwt_svc: JWTService | None = None


def get_jwt_service() -> JWTService:
    global _jwt_svc
    if _jwt_svc is None:
        _jwt_svc = JWTService()
    return _jwt_svc
