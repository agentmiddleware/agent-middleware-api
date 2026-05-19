from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import SigningKeyModel


class SigningKeyError(RuntimeError):
    """Raised when trust-plane signing or verification cannot proceed."""


def canonical_json(payload: dict[str, Any]) -> str:
    """Serialize a payload into stable JSON before hashing or signing."""

    def normalize(value: Any) -> Any:
        if isinstance(value, Decimal):
            normalized = value.normalize()
            if normalized == normalized.to_integral():
                return format(normalized, "f")
            return format(normalized, "f")
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value

    return json.dumps(normalize(payload), separators=(",", ":"), sort_keys=True)


def sha256_hex(payload: dict[str, Any] | str | bytes) -> str:
    if isinstance(payload, dict):
        data = canonical_json(payload).encode()
    elif isinstance(payload, str):
        data = payload.encode()
    else:
        data = payload
    return hashlib.sha256(data).hexdigest()


class SigningKeyService:
    """Ed25519 signing helper with DB-backed public key metadata."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._private_key: Ed25519PrivateKey | None = None
        self._key_id = self._settings.TRUST_SIGNING_KEY_ID

    def _load_private_key(self) -> Ed25519PrivateKey:
        if self._private_key:
            return self._private_key

        configured = self._settings.TRUST_SIGNING_PRIVATE_KEY_B64.strip()
        if configured:
            try:
                raw = base64.b64decode(configured)
                self._private_key = Ed25519PrivateKey.from_private_bytes(raw)
                return self._private_key
            except Exception as exc:  # pragma: no cover - defensive config guard
                raise SigningKeyError("invalid_trust_signing_private_key") from exc

        if self._settings.TRUST_MODE_ENABLED:
            raise SigningKeyError("trust_signing_private_key_required")

        # Development/test fallback is deliberately process-ephemeral. It lets
        # local tests verify signatures without silently persisting a private key.
        self._private_key = Ed25519PrivateKey.generate()
        return self._private_key

    def _public_key_b64(self) -> str:
        public_key = self._load_private_key().public_key()
        raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    async def ensure_active_key(self) -> SigningKeyModel:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(SigningKeyModel).where(SigningKeyModel.key_id == self._key_id)
            )
            key = result.scalar_one_or_none()
            public_key_b64 = self._public_key_b64()
            if key:
                if key.public_key_b64 != public_key_b64:
                    key.public_key_b64 = public_key_b64
                    key.status = "active"
                    key.activated_at = datetime.now(timezone.utc)
                session.add(key)
            else:
                key = SigningKeyModel(
                    key_id=self._key_id,
                    public_key_b64=public_key_b64,
                    status="active",
                    activated_at=datetime.now(timezone.utc),
                )
                session.add(key)
            await session.commit()
            return key

    async def get_public_key(self, key_id: str) -> SigningKeyModel | None:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(SigningKeyModel).where(SigningKeyModel.key_id == key_id)
            )
            return result.scalar_one_or_none()

    async def sign_payload(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        key = await self.ensure_active_key()
        signing_payload = dict(payload)
        signing_payload.setdefault("alg", "Ed25519")
        signing_payload.setdefault("kid", key.key_id)
        payload_hash = sha256_hex(signing_payload)
        signing_payload.setdefault("payload_hash", payload_hash)
        signature = self._load_private_key().sign(canonical_json(signing_payload).encode())
        return base64.b64encode(signature).decode(), key.key_id, payload_hash

    async def verify_payload(
        self,
        payload: dict[str, Any],
        *,
        signature: str,
        key_id: str,
    ) -> bool:
        key = await self.get_public_key(key_id)
        if not key or key.status == "disabled":
            return False
        public_raw = base64.b64decode(key.public_key_b64)
        public_key = Ed25519PublicKey.from_public_bytes(public_raw)
        try:
            public_key.verify(base64.b64decode(signature), canonical_json(payload).encode())
            return True
        except InvalidSignature:
            return False


_signing_key_service: SigningKeyService | None = None


def get_signing_key_service() -> SigningKeyService:
    global _signing_key_service
    if _signing_key_service is None:
        _signing_key_service = SigningKeyService()
    return _signing_key_service
