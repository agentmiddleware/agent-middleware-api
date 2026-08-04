"""JWT access token creation and verification.

Uses Ed25519 for signing (reuse existing trust-plane signing key).
Short-lived: 15 min access, 7 day refresh.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings
from app.services.signing_keys import get_signing_key_service


JWT_ALGORITHM = "EdDSA"
JWT_ISSUER = "agent-middleware-api"
JWT_ACCESS_EXPIRY = 900   # 15 minutes
JWT_REFRESH_EXPIRY = 604800  # 7 days


@dataclass(frozen=True)
class JWTPayload:
    sub: str          # wallet_id
    key_id: str | None
    scopes: list[str]
    iat: datetime
    exp: datetime
    iss: str
    aud: str
    jti: str          # unique token id
    type: str         # access | refresh


class JWTError(Exception):
    pass


class JWTService:
    """Create and verify JWT access tokens signed with Ed25519."""

    def __init__(self) -> None:
        self._sk_svc = get_signing_key_service()

    async def _get_signing_key(self) -> tuple[bytes, str]:
        """Return (private_key_bytes, key_id)."""
        # Reuse the trust-plane Ed25519 signing key
        settings = get_settings()
        b64_key = settings.TRUST_SIGNING_PRIVATE_KEY_B64
        if not b64_key:
            raise JWTError("signing_key_not_configured")
        import base64
        private_key = base64.b64decode(b64_key)
        # Get key_id from the signing key service
        _, key_id = await self._sk_svc.sign_payload({"jwt": "key_probe"})
        return private_key, key_id

    async def create_access_token(
        self,
        wallet_id: str,
        key_id: str | None,
        scopes: list[str],
    ) -> str:
        """Create a short-lived access token."""
        private_key, signing_key_id = await self._get_signing_key()
        now = datetime.now(timezone.utc)
        jti = f"jwt-{uuid.uuid4().hex[:16]}"

        payload = {
            "sub": wallet_id,
            "key_id": key_id,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(seconds=JWT_ACCESS_EXPIRY),
            "iss": JWT_ISSUER,
            "aud": JWT_ISSUER,
            "jti": jti,
            "type": "access",
        }

        token = jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)
        return token

    async def create_refresh_token(self, wallet_id: str) -> str:
        """Create a long-lived refresh token."""
        private_key, _ = await self._get_signing_key()
        now = datetime.now(timezone.utc)
        jti = f"jwt-refresh-{uuid.uuid4().hex[:16]}"

        payload = {
            "sub": wallet_id,
            "iat": now,
            "exp": now + timedelta(seconds=JWT_REFRESH_EXPIRY),
            "iss": JWT_ISSUER,
            "aud": JWT_ISSUER,
            "jti": jti,
            "type": "refresh",
        }

        token = jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)
        return token

    async def verify_token(self, token: str, token_type: str = "access") -> JWTPayload:
        """Verify a JWT and return its payload."""
        # Get public key for verification
        public_key = await self._sk_svc.get_public_key_bytes()
        if not public_key:
            raise JWTError("public_key_not_available")

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                audience=JWT_ISSUER,
            )
        except jwt.ExpiredSignatureError:
            raise JWTError("token_expired")
        except jwt.InvalidTokenError as e:
            raise JWTError(f"invalid_token: {e}")

        if payload.get("type") != token_type:
            raise JWTError(f"token_type_mismatch: expected {token_type}")

        return JWTPayload(
            sub=payload["sub"],
            key_id=payload.get("key_id"),
            scopes=payload.get("scopes", []),
            iat=payload["iat"],
            exp=payload["exp"],
            iss=payload["iss"],
            aud=payload["aud"],
            jti=payload["jti"],
            type=payload["type"],
        )

    async def verify_access_token(self, token: str) -> JWTPayload:
        return await self.verify_token(token, token_type="access")

    async def verify_refresh_token(self, token: str) -> JWTPayload:
        return await self.verify_token(token, token_type="refresh")


# Module-level singleton
_jwt_svc: JWTService | None = None


def get_jwt_service() -> JWTService:
    global _jwt_svc
    if _jwt_svc is None:
        _jwt_svc = JWTService()
    return _jwt_svc
