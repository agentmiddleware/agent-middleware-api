"""
Signed receipt verification endpoints.

Lets a wallet owner (or auditor with the public key) confirm that ledger
entries are authentic and that a wallet's receipt chain is unbroken.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..core.auth import AuthContext, get_auth_context
from ..db.database import get_session_factory
from ..db.models import LedgerEntryModel
from ..services.receipts import get_receipt_service

router = APIRouter(prefix="/v1/billing/receipts", tags=["billing"])


def _receipt_dict(entry: LedgerEntryModel) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "wallet_id": entry.wallet_id,
        "action": entry.action,
        "amount": str(entry.amount),
        "balance_after": str(entry.balance_after),
        "service_category": entry.service_category,
        "description": entry.description,
        "chain_seq": entry.chain_seq,
        "prev_hash": entry.prev_hash,
        "entry_hash": entry.entry_hash,
        "signature": entry.signature,
        "receipt_alg": entry.receipt_alg,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }


@router.get("/public-key", summary="Receipt signing public key")
async def receipt_public_key() -> dict[str, Any]:
    """Public key (and algorithm) used to sign receipts. Public on purpose so
    third parties can verify receipts offline."""
    receipts = get_receipt_service()
    return {
        "algorithm": receipts.algorithm,
        "public_key": receipts.public_key_b64(),
        "encoding": "base64",
        "verifiable_offline": receipts.algorithm == "ed25519",
    }


@router.get("/entry/{entry_id}", summary="Get a signed receipt for a ledger entry")
async def get_receipt(
    entry_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(LedgerEntryModel).where(LedgerEntryModel.entry_id == entry_id)
        )
        entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Ledger entry not found."},
        )
    auth.require_wallet_access(entry.wallet_id)

    receipts = get_receipt_service()
    return {
        "receipt": _receipt_dict(entry),
        "verified": receipts.verify_entry(entry),
        "algorithm": receipts.algorithm,
    }


@router.get("/wallet/{wallet_id}/verify", summary="Verify a wallet's receipt chain")
async def verify_chain(
    wallet_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    auth.require_wallet_access(wallet_id)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(LedgerEntryModel)
            .where(LedgerEntryModel.wallet_id == wallet_id)
            .order_by(LedgerEntryModel.chain_seq.asc())
        )
        entries = list(result.scalars().all())
    receipts = get_receipt_service()

    checked = 0
    prev_hash: str | None = None
    broken: list[dict[str, Any]] = []

    for entry in entries:
        if entry.chain_seq is None or entry.entry_hash is None or not entry.signature:
            broken.append(
                {"entry_id": entry.entry_id, "reason": "unsigned_legacy_entry"}
            )
            continue
        if (entry.prev_hash or None) != (prev_hash or None):
            broken.append(
                {
                    "entry_id": entry.entry_id,
                    "chain_seq": entry.chain_seq,
                    "reason": "broken_link",
                }
            )
        if not receipts.verify_entry(entry):
            broken.append(
                {
                    "entry_id": entry.entry_id,
                    "chain_seq": entry.chain_seq,
                    "reason": "invalid_signature_or_hash",
                }
            )
        prev_hash = entry.entry_hash
        checked += 1

    return {
        "wallet_id": wallet_id,
        "entries_total": len(entries),
        "entries_checked": checked,
        "chain_valid": len(entries) > 0 and len(broken) == 0,
        "broken": broken,
        "algorithm": receipts.algorithm,
    }
