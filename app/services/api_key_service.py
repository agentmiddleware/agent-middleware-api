"""
API Key Rotation Service for wallet security.

Handles API key creation, rotation, and revocation for compromised wallets.
Supports automatic rotation on suspicious activity detection.

Architecture:
1. Keys are stored hashed (SHA-256) in the database
2. Only the key prefix and masked key are ever shown
3. Rotation creates new key and optionally revokes old ones
4. Emergency revocation immediately invalidates all keys
"""

import hashlib
import json
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, update

from ..db.database import get_session_factory
from ..db.models import APIKeyModel, KeyRotationLogModel, WalletModel
from ..schemas.billing import (
    APIKeyStatus,
    RotationType,
)

logger = logging.getLogger(__name__)

API_KEY_LENGTH = 32
API_KEY_PREFIX_LENGTH = 8


class APIKeyError(Exception):
    """Base exception for API key operations."""
    pass


class KeyNotFoundError(APIKeyError):
    """Raised when an API key is not found."""
    def __init__(self, key_id: str):
        self.key_id = key_id
        super().__init__(f"API key not found: {key_id}")


class WalletNotFoundError(APIKeyError):
    """Raised when a wallet is not found."""
    def __init__(self, wallet_id: str):
        self.wallet_id = wallet_id
        super().__init__(f"Wallet not found: {wallet_id}")


class KeyExpiredError(APIKeyError):
    """Raised when an API key has expired."""
    pass


class KeyRevokedError(APIKeyError):
    """Raised when an API key has been revoked."""
    pass


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        tuple: (full_key, key_hash, key_prefix)
    """
    full_key = f"b2a_{secrets.token_urlsafe(API_KEY_LENGTH)}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:API_KEY_PREFIX_LENGTH]
    return full_key, key_hash, key_prefix


def mask_key(key: str) -> str:
    """Mask an API key for safe display."""
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


class APIKeyService:
    """
    Manages API keys for wallet authentication and key rotation.

    Features:
    - Create new API keys with optional expiration
    - Rotate keys manually or automatically
    - Emergency revocation for compromised wallets
    - Usage tracking and audit logging
    """

    def __init__(self):
        self._session_factory = get_session_factory

    async def create_key(
        self,
        wallet_id: str,
        key_name: str = "default",
        expires_in_days: int | None = None,
    ) -> dict:
        """
        Create a new API key for a wallet.

        Args:
            wallet_id: Wallet to create key for
            key_name: Human-readable name for the key
            expires_in_days: Optional expiration in days

        Returns:
            {
                "key_id": str,
                "wallet_id": str,
                "api_key": str,
                "key_prefix": str,
                "status": str,
                "key_name": str,
                "created_at": datetime,
                "expires_at": datetime | None,
            }
        """
        async with self._session_factory()() as session:
            result = await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )
            wallet = result.scalar_one_or_none()
            if not wallet:
                raise WalletNotFoundError(wallet_id)

        full_key, key_hash, key_prefix = generate_api_key()
        key_id = f"key_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        expires_at = None

        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)

        async with self._session_factory()() as session:
            api_key = APIKeyModel(
                key_id=key_id,
                wallet_id=wallet_id,
                key_hash=key_hash,
                key_prefix=key_prefix,
                status=APIKeyStatus.ACTIVE.value,
                metadata_json=json.dumps({"name": key_name}),
                expires_at=expires_at,
            )
            session.add(api_key)
            await session.commit()

        logger.info(f"Created API key {key_id} for wallet {wallet_id}")

        return {
            "key_id": key_id,
            "wallet_id": wallet_id,
            "api_key": full_key,
            "key_prefix": key_prefix,
            "status": APIKeyStatus.ACTIVE.value,
            "key_name": key_name,
            "created_at": now,
            "expires_at": expires_at,
        }

    async def get_keys(self, wallet_id: str) -> dict:
        """
        Get all API keys for a wallet (masked).

        Args:
            wallet_id: Wallet to get keys for

        Returns:
            {
                "wallet_id": str,
                "keys": list[APIKeyResponse],
                "total_active": int,
                "total_revoked": int,
            }
        """
        async with self._session_factory()() as session:
            wallet_result = await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )
            if not wallet_result.scalar_one_or_none():
                raise WalletNotFoundError(wallet_id)

            result = await session.execute(
                select(APIKeyModel).where(APIKeyModel.wallet_id == wallet_id)
            )
            keys = list(result.scalars().all())

        response_keys = []
        total_active = 0
        total_revoked = 0

        for key in keys:
            metadata = {}
            if key.metadata_json:
                try:
                    metadata = json.loads(key.metadata_json)
                except json.JSONDecodeError:
                    pass

            response_keys.append({
                "key_id": key.key_id,
                "wallet_id": key.wallet_id,
                "key_prefix": key.key_prefix,
                "masked_key": f"{key.key_prefix}...****",
                "status": key.status,
                "key_name": metadata.get("name", "default"),
                "rotation_count": key.rotation_count,
                "last_used_at": key.last_used_at,
                "created_at": key.created_at,
                "expires_at": key.expires_at,
            })

            if key.status == APIKeyStatus.ACTIVE.value:
                total_active += 1
            elif key.status == APIKeyStatus.REVOKED.value:
                total_revoked += 1

        return {
            "wallet_id": wallet_id,
            "keys": response_keys,
            "total_active": total_active,
            "total_revoked": total_revoked,
        }

    async def validate_key(self, api_key: str) -> Optional[APIKeyModel]:
        """
        Validate an API key and return the key model if valid.

        Args:
            api_key: The API key to validate

        Returns:
            APIKeyModel if valid, None if invalid
        """
        if not api_key or len(api_key) < 8:
            return None

        key_prefix = api_key[:API_KEY_PREFIX_LENGTH]
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        async with self._session_factory()() as session:
            result = await session.execute(
                select(APIKeyModel).where(
                    APIKeyModel.key_prefix == key_prefix,
                    APIKeyModel.status == APIKeyStatus.ACTIVE.value,
                )
            )
            key = result.scalar_one_or_none()

            if not key:
                return None

            if key.key_hash != key_hash:
                return None

            now = datetime.now(timezone.utc)
            expires_at = key.expires_at
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at and expires_at < now:
                return None

            key.last_used_at = now
            session.add(key)
            await session.commit()

        return key

    async def rotate_key(
        self,
        wallet_id: str,
        key_id: str | None = None,
        revoke_old: bool = False,
        reason: str = "manual_rotation",
        triggered_by: str = "user",
        ip_address: str | None = None,
    ) -> dict:
        """
        Rotate an API key.

        Args:
            wallet_id: Wallet owning the key
            key_id: Specific key to rotate (None = create new key only)
            revoke_old: Whether to revoke the old key
            reason: Reason for rotation
            triggered_by: What triggered the rotation
            ip_address: IP address of the requester

        Returns:
            {
                "rotation_id": str,
                "wallet_id": str,
                "old_key_id": str | None,
                "new_key": dict | None,
                "rotation_type": str,
                "revoked_keys": list[str],
                "created_at": datetime,
            }
        """
        old_key_id = None
        now = datetime.now(timezone.utc)
        rotation_id = f"rot_{uuid4().hex[:12]}"
        rotation_type = (
            RotationType.MANUAL.value if triggered_by == "user"
            else RotationType.AUTOMATIC.value
        )

        async with self._session_factory()() as session:
            wallet_result = await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )
            if not wallet_result.scalar_one_or_none():
                raise WalletNotFoundError(wallet_id)

            if key_id:
                result = await session.execute(
                    select(APIKeyModel).where(
                        APIKeyModel.key_id == key_id,
                        APIKeyModel.wallet_id == wallet_id,
                    )
                )
                old_key = result.scalar_one_or_none()

                if not old_key:
                    raise KeyNotFoundError(key_id)

                old_key_id = old_key.key_id

                if revoke_old:
                    old_key.status = APIKeyStatus.REVOKED.value
                    old_key.revoked_at = now
                    old_key.revoke_reason = reason

            full_key, key_hash, key_prefix = generate_api_key()
            new_key_id = f"key_{uuid4().hex[:12]}"
            new_key_prefix = key_prefix

            new_key = APIKeyModel(
                key_id=new_key_id,
                wallet_id=wallet_id,
                key_hash=key_hash,
                key_prefix=new_key_prefix,
                status=APIKeyStatus.ACTIVE.value,
            )
            session.add(new_key)

            if old_key_id:
                await session.execute(
                    update(APIKeyModel)
                    .where(APIKeyModel.key_id == old_key_id)
                    .values(
                        rotation_count=APIKeyModel.rotation_count + 1,
                        last_rotated_at=now,
                    )
                )

            log_entry = KeyRotationLogModel(
                log_id=rotation_id,
                key_id=new_key_id,
                wallet_id=wallet_id,
                rotation_type=rotation_type,
                old_key_id=old_key_id,
                new_key_id=new_key_id,
                trigger_reason=reason,
                triggered_by=triggered_by,
                ip_address=ip_address,
                created_at=now,
            )
            session.add(log_entry)

            await session.commit()

        new_key_data = {
            "key_id": new_key_id,
            "wallet_id": wallet_id,
            "api_key": full_key,
            "key_prefix": new_key_prefix,
            "status": APIKeyStatus.ACTIVE.value,
            "key_name": "rotated_key",
            "created_at": now,
            "expires_at": None,
        }

        logger.info(
            f"Rotated API key for wallet {wallet_id}: "
            f"old={old_key_id}, new={new_key_id}, reason={reason}"
        )

        return {
            "rotation_id": rotation_id,
            "wallet_id": wallet_id,
            "old_key_id": old_key_id,
            "new_key": new_key_data,
            "rotation_type": rotation_type,
            "revoked_keys": [old_key_id] if (old_key_id and revoke_old) else [],
            "created_at": now,
        }

    async def revoke_key(
        self,
        wallet_id: str,
        key_id: str,
        reason: str = "user_request",
    ) -> bool:
        """
        Revoke an API key.

        Args:
            wallet_id: Wallet owning the key
            key_id: Key to revoke
            reason: Reason for revocation

        Returns:
            True if revoked successfully
        """
        async with self._session_factory()() as session:
            result = await session.execute(
                select(APIKeyModel).where(
                    APIKeyModel.key_id == key_id,
                    APIKeyModel.wallet_id == wallet_id,
                )
            )
            key = result.scalar_one_or_none()

            if not key:
                raise KeyNotFoundError(key_id)

            key.status = APIKeyStatus.REVOKED.value
            key.revoked_at = datetime.now(timezone.utc)
            key.revoke_reason = reason
            session.add(key)
            await session.commit()

        logger.warning(f"Revoked API key {key_id} for wallet {wallet_id}: {reason}")
        return True

    async def emergency_revocation(
        self,
        wallet_id: str,
        reason: str = "security_incident",
        create_new_key: bool = True,
    ) -> dict:
        """
        Immediately revoke all keys for a wallet and optionally create new ones.

        Args:
            wallet_id: Wallet to revoke keys for
            reason: Reason for emergency revocation
            create_new_key: Whether to create a new emergency key

        Returns:
            {
                "wallet_id": str,
                "revoked_keys": list[str],
                "new_key": dict | None,
                "created_at": datetime,
            }
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory()() as session:
            wallet_result = await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )
            if not wallet_result.scalar_one_or_none():
                raise WalletNotFoundError(wallet_id)

            result = await session.execute(
                select(APIKeyModel).where(
                    APIKeyModel.wallet_id == wallet_id,
                    APIKeyModel.status == APIKeyStatus.ACTIVE.value,
                )
            )
            active_keys = list(result.scalars().all())

            revoked_key_ids = []
            for key in active_keys:
                key.status = APIKeyStatus.REVOKED.value
                key.revoked_at = now
                key.revoke_reason = f"EMERGENCY: {reason}"
                session.add(key)
                revoked_key_ids.append(key.key_id)

            log_entry = KeyRotationLogModel(
                log_id=f"rot_{uuid4().hex[:12]}",
                key_id="all",
                wallet_id=wallet_id,
                rotation_type=RotationType.EMERGENCY.value,
                trigger_reason=reason,
                triggered_by="emergency_system",
                created_at=now,
            )
            session.add(log_entry)

            new_key_data = None
            if create_new_key:
                full_key, key_hash, key_prefix = generate_api_key()
                new_key_id = f"key_{uuid4().hex[:12]}"
                emergency_key = APIKeyModel(
                    key_id=new_key_id,
                    wallet_id=wallet_id,
                    key_hash=key_hash,
                    key_prefix=key_prefix,
                    status=APIKeyStatus.ACTIVE.value,
                    metadata_json=json.dumps({"name": "emergency_key"}),
                )
                session.add(emergency_key)
                new_key_data = {
                    "key_id": new_key_id,
                    "wallet_id": wallet_id,
                    "api_key": full_key,
                    "key_prefix": key_prefix,
                    "status": APIKeyStatus.ACTIVE.value,
                    "key_name": "emergency_key",
                    "created_at": now,
                    "expires_at": None,
                }

            await session.commit()

        logger.critical(
            f"EMERGENCY revocation for wallet {wallet_id}: "
            f"revoked {len(revoked_key_ids)} keys, reason={reason}"
        )

        from ..services.notifications import get_notification_service
        notifications = get_notification_service()
        await notifications.send_security_alert(
            wallet_id=wallet_id,
            alert_type="emergency_key_revocation",
            message=f"All API keys revoked for wallet {wallet_id}. Reason: {reason}",
        )

        return {
            "wallet_id": wallet_id,
            "revoked_keys": revoked_key_ids,
            "new_key": new_key_data,
            "created_at": now,
        }

    async def get_rotation_logs(
        self,
        wallet_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get rotation audit logs for a wallet.

        Args:
            wallet_id: Wallet to get logs for
            limit: Maximum number of logs to return

        Returns:
            list of rotation log entries
        """
        async with self._session_factory()() as session:
            result = await session.execute(
                select(KeyRotationLogModel)
                .where(KeyRotationLogModel.wallet_id == wallet_id)
                .order_by(KeyRotationLogModel.created_at.desc())
                .limit(limit)
            )
            logs = list(result.scalars().all())

        return [
            {
                "log_id": log.log_id,
                "key_id": log.key_id,
                "wallet_id": log.wallet_id,
                "rotation_type": log.rotation_type,
                "old_key_id": log.old_key_id,
                "new_key_id": log.new_key_id,
                "trigger_reason": log.trigger_reason,
                "triggered_by": log.triggered_by,
                "created_at": log.created_at,
            }
            for log in logs
        ]

    async def auto_rotate_on_suspicious_activity(
        self,
        wallet_id: str,
        reason: str,
    ) -> dict:
        """
        Automatically rotate keys when suspicious activity is detected.

        Args:
            wallet_id: Wallet to rotate keys for
            reason: Reason for automatic rotation

        Returns:
            Rotation result dict
        """
        async with self._session_factory()() as session:
            result = await session.execute(
                select(APIKeyModel).where(
                    APIKeyModel.wallet_id == wallet_id,
                    APIKeyModel.status == APIKeyStatus.ACTIVE.value,
                )
            )
            active_key = result.scalars().first()

        key_id = active_key.key_id if active_key else None

        result = await self.rotate_key(
            wallet_id=wallet_id,
            key_id=key_id,
            revoke_old=True,
            reason=f"AUTOMATIC: {reason}",
            triggered_by="security_system",
        )
        result["rotation_type"] = RotationType.AUTOMATIC.value

        return result


_api_key_service: Optional[APIKeyService] = None


def get_api_key_service() -> APIKeyService:
    """Get or create the APIKeyService singleton."""
    global _api_key_service
    if _api_key_service is None:
        _api_key_service = APIKeyService()
    return _api_key_service
