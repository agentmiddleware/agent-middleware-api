"""Text generation API backed by Content Factory (durable + LLM)."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, status

from ..audit.lightweight import record_audit
from ..core.auth import AuthContext, get_auth_context
from ..core.dependencies import get_content_factory
from ..schemas.content_generation import (
    ContentGenerateRequest,
    ContentGenerateResponse,
    ContentRecordResponse,
)
from ..services.content_factory import ContentFactory

router = APIRouter(
    prefix="/v1/content",
    tags=["Content Factory — Text Generation"],
    responses={
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key"},
    },
)


def _audit_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


@router.post(
    "/generate",
    response_model=ContentGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate text via LLM (durable when simulation is off)",
)
async def generate_content_text(
    request: ContentGenerateRequest,
    auth: AuthContext = Depends(get_auth_context),
    factory: ContentFactory = Depends(get_content_factory),
):
    try:
        result = await factory.generate_llm_text(
            prompt=request.prompt, model=request.model
        )
    except RuntimeError as exc:
        record_audit(
            "content_factory.generate",
            actor_source=auth.source,
            key_id=auth.key_id,
            wallet_id=auth.wallet_id,
            outcome="error",
            payload_hash=_audit_hash(
                {"error": str(exc), "model": request.model, "prompt": request.prompt}
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "llm_unavailable",
                "message": str(exc),
            },
        ) from exc

    audit_basis = {
        "content_id": result["content_id"],
        "model": result["model"],
        "prompt": request.prompt,
        "requested_model": request.model,
    }
    record_audit(
        "content_factory.generate",
        actor_source=auth.source,
        key_id=auth.key_id,
        wallet_id=auth.wallet_id,
        outcome="ok",
        payload_hash=_audit_hash(audit_basis),
        content_id=result["content_id"],
    )
    return ContentGenerateResponse(
        content_id=result["content_id"],
        text=result["text"],
        model=result["model"],
        prompt_hash=result["prompt_hash"],
        output_hash=result["output_hash"],
        provenance=result["provenance"],
    )


@router.get(
    "/{content_id}",
    response_model=ContentRecordResponse,
    summary="Get persisted generation by id",
)
async def get_content_record(
    content_id: str,
    auth: AuthContext = Depends(get_auth_context),
    factory: ContentFactory = Depends(get_content_factory),
):
    audit_h = _audit_hash({"content_id": content_id})
    row = await factory.get_llm_generation(content_id)
    if not row:
        record_audit(
            "content_factory.get",
            actor_source=auth.source,
            key_id=auth.key_id,
            wallet_id=auth.wallet_id,
            outcome="not_found",
            payload_hash=audit_h,
            content_id=content_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Unknown content_id."},
        )

    record_audit(
        "content_factory.get",
        actor_source=auth.source,
        key_id=auth.key_id,
        wallet_id=auth.wallet_id,
        outcome="ok",
        payload_hash=audit_h,
        content_id=content_id,
    )
    ca = row["created_at"]
    ua = row.get("updated_at")
    return ContentRecordResponse(
        content_id=row["content_id"],
        prompt_hash=row["prompt_hash"],
        output_hash=row["output_hash"],
        model=row["model"],
        provenance=row["provenance"],
        text=row["text"],
        created_at=ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
        updated_at=ua.isoformat()
        if ua is not None and hasattr(ua, "isoformat")
        else (str(ua) if ua is not None else None),
    )
