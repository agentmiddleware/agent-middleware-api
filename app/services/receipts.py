"""
Signed Receipts
===============
Makes ledger entries tamper-evident and independently verifiable.

Each entry is hash-chained per wallet (``prev_hash`` links to the previous
entry's ``entry_hash``) and signed over a canonical payload. With an Ed25519
key, any third party can verify a receipt using the public key from
``GET /v1/billing/receipts/public-key`` — without trusting the database.

Tampering with any historical entry changes its ``entry_hash``, which breaks the
``prev_hash`` linkage of every later entry and invalidates the signature.

Signing backend:
- Ed25519 (via ``cryptography``) when available — asymmetric, independently
  verifiable. This is the default.
- HMAC-SHA256 fallback when ``cryptography`` is absent — tamper-evident but only
  verifiable by a holder of the server secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from decimal import Decimal
from functools import lru_cache
from typing import Any

from ..core.config import get_settings
from ..db.models import LedgerEntryModel

logger = logging.getLogger(__name__)

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    _ED25519_AVAILABLE = True
except Exception:  # pragma: no cover - only when cryptography is missing
    _ED25519_AVAILABLE = False


def _fmt_amount(value: Decimal | None) -> str:
    """Canonical fixed-precision string so signing and verification agree
    regardless of how the database round-trips the Decimal's exponent."""
    if value is None:
        return ""
    return f"{Decimal(value):.8f}"


class ReceiptService:
    """Signs and verifies ledger receipts."""

    def __init__(self, signing_key_b64: str = "", hmac_secret: str = ""):
        self._ed_private: Any = None
        self._ed_public: Any = None
        self._hmac_secret: bytes = b""

        if _ED25519_AVAILABLE:
            self.algorithm = "ed25519"
            if signing_key_b64:
                seed = base64.b64decode(signing_key_b64)
                self._ed_private = Ed25519PrivateKey.from_private_bytes(seed)
            else:
                self._ed_private = Ed25519PrivateKey.generate()
                logger.warning(
                    "RECEIPT_SIGNING_KEY not set; using an ephemeral Ed25519 key. "
                    "Receipts will not verify across restarts — set "
                    "RECEIPT_SIGNING_KEY in production."
                )
            self._ed_public = self._ed_private.public_key()
        else:
            self.algorithm = "hmac-sha256"
            if hmac_secret:
                self._hmac_secret = hmac_secret.encode()
            else:
                self._hmac_secret = base64.b64encode(os.urandom(32))
                logger.warning(
                    "cryptography unavailable and RECEIPT_HMAC_SECRET not set; "
                    "using an ephemeral HMAC secret (dev only)."
                )

    def canonical_payload(
        self, entry: LedgerEntryModel, prev_hash: str | None
    ) -> bytes:
        """Deterministic byte payload bound by the hash and signature."""
        payload = {
            "entry_id": entry.entry_id,
            "wallet_id": entry.wallet_id,
            "action": entry.action,
            "amount": _fmt_amount(entry.amount),
            "balance_after": _fmt_amount(entry.balance_after),
            "service_category": entry.service_category or "",
            "request_path": entry.request_path or "",
            "description": entry.description or "",
            "chain_seq": entry.chain_seq,
            "prev_hash": prev_hash or "",
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def hash_payload(self, payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def sign(self, payload: bytes) -> str:
        if self.algorithm == "ed25519":
            sig = self._ed_private.sign(payload)
        else:
            sig = hmac.new(self._hmac_secret, payload, hashlib.sha256).digest()
        return base64.b64encode(sig).decode()

    def verify(self, payload: bytes, signature_b64: str) -> bool:
        try:
            sig = base64.b64decode(signature_b64)
        except Exception:
            return False

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
        """Base64 raw Ed25519 public key, or None for the HMAC backend."""
        if self.algorithm == "ed25519" and self._ed_public is not None:
            raw = self._ed_public.public_bytes(Encoding.Raw, PublicFormat.Raw)
            return base64.b64encode(raw).decode()
        return None

    def verify_entry(self, entry: LedgerEntryModel) -> bool:
        """Verify a stored entry's hash and signature against its content."""
        if not entry.signature or entry.entry_hash is None:
            return False
        payload = self.canonical_payload(entry, entry.prev_hash)
        if self.hash_payload(payload) != entry.entry_hash:
            return False
        return self.verify(payload, entry.signature)


def build_signed_ledger_entry(
    receipts: ReceiptService,
    *,
    wallet: Any,
    entry_id: str,
    action: str,
    amount: Decimal,
    balance_after: Decimal,
    **fields: Any,
) -> LedgerEntryModel:
    """Construct a ledger entry that extends the wallet's signed receipt chain.

    The wallet row is expected to be locked by the caller's transaction, so
    reading/advancing ``receipt_seq`` and ``last_receipt_hash`` is race-free.
    """
    seq = (wallet.receipt_seq or 0) + 1
    prev_hash = wallet.last_receipt_hash
    entry = LedgerEntryModel(
        entry_id=entry_id,
        wallet_id=wallet.wallet_id,
        action=action,
        amount=amount,
        balance_after=balance_after,
        chain_seq=seq,
        prev_hash=prev_hash,
        **fields,
    )
    payload = receipts.canonical_payload(entry, prev_hash)
    entry.entry_hash = receipts.hash_payload(payload)
    entry.signature = receipts.sign(payload)
    entry.receipt_alg = receipts.algorithm

    wallet.receipt_seq = seq
    wallet.last_receipt_hash = entry.entry_hash
    return entry


@lru_cache()
def get_receipt_service() -> ReceiptService:
    settings = get_settings()
    return ReceiptService(settings.RECEIPT_SIGNING_KEY, settings.RECEIPT_HMAC_SECRET)
