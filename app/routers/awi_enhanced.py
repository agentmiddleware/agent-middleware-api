"""
AWI Enhanced Router — Phase 9
=============================

New endpoints for Phase 9 AWI features:
- Passkey/WebAuthn challenge and verification
- Bidirectional DOM synchronization
- RAG-based memory queries

Based on arXiv:2506.10953v1 gap analysis.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..schemas.awi_enhanced import (
    DOMBridgeSessionRequest,
    DOMBridgeSessionResponse,
    DOMRepresentationType,
    DOMStateRequest,
    DOMStateResponse,
    DOMSyncRequest,
    DOMSyncResponse,
    MemoryDeleteRequest,
    MemoryIndexRequest,
    MemoryIndexResponse,
    PasskeyChallengeRequest,
    PasskeyChallengeResponse,
    PasskeySessionStatus,
    PasskeyVerifyRequest,
    PasskeyVerifyResponse,
    RAGQueryRequest,
    RAGQueryResponse,
    SessionContextRequest,
    SessionContextResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/awi", tags=["AWI Enhanced"])


# ─────────────────────────────────────────────────────────────────────────────
# Passkey / WebAuthn Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/passkey/challenge",
    response_model=PasskeyChallengeResponse,
    summary="Create passkey challenge",
    description="Create a WebAuthn challenge for high-risk AWI action verification.",
)
async def create_passkey_challenge(request: PasskeyChallengeRequest):
    """
    Create a WebAuthn registration/authentication challenge.

    The client should use navigator.credentials.get() with the returned
    options, then call /passkey/verify with the credential response.
    """
    from ..services.webauthn_provider import get_webauthn_provider

    webauthn = get_webauthn_provider()

    requires = await webauthn.requires_passkey(request.session_id, request.action)
    if not requires:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "passkey_not_required",
                "message": f"Action '{request.action}' does not require passkey verification",
            },
        )

    try:
        challenge = await webauthn.create_challenge(
            session_id=request.session_id,
            action=request.action,
        )
        return PasskeyChallengeResponse(**challenge)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "challenge_failed", "message": str(e)},
        )
    except Exception as e:
        logger.exception("Failed to create passkey challenge")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "challenge_creation_failed", "message": str(e)},
        )


@router.post(
    "/passkey/verify",
    response_model=PasskeyVerifyResponse,
    summary="Verify passkey response",
    description="Verify the WebAuthn credential response from the client.",
)
async def verify_passkey(request: PasskeyVerifyRequest):
    """
    Verify WebAuthn assertion response.

    After successful verification, the action is marked as verified
    for 5 minutes (configurable).
    """
    from ..services.webauthn_provider import get_webauthn_provider

    webauthn = get_webauthn_provider()

    try:
        result = await webauthn.verify_response(
            challenge_id=request.challenge_id,
            credential=request.credential,
        )
        return PasskeyVerifyResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "verification_failed", "message": str(e)},
        )
    except Exception as e:
        logger.exception("Passkey verification error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "verification_error", "message": str(e)},
        )


@router.get(
    "/passkey/status/{session_id}/{action}",
    response_model=PasskeySessionStatus,
    summary="Check passkey verification status",
    description="Check if a session:action pair has valid passkey verification.",
)
async def check_passkey_status(session_id: str, action: str):
    """Check if the action is currently verified for this session."""
    from ..services.webauthn_provider import get_webauthn_provider

    webauthn = get_webauthn_provider()

    status_info = await webauthn.get_verification_status(session_id, action)
    return PasskeySessionStatus(**status_info)


@router.delete(
    "/passkey/invalidate/{session_id}",
    summary="Invalidate passkey verifications",
    description="Invalidate all passkey verifications for a session.",
)
async def invalidate_passkey(session_id: str, action: str | None = None):
    """Invalidate passkey verifications for a session."""
    from ..services.webauthn_provider import get_webauthn_provider

    webauthn = get_webauthn_provider()

    invalidated = await webauthn.invalidate_verification(session_id, action)

    return {
        "session_id": session_id,
        "action": action,
        "invalidated_count": invalidated,
    }


@router.get(
    "/passkey/high-risk-actions",
    summary="List high-risk actions",
    description="Get list of actions that require passkey verification.",
)
async def list_high_risk_actions():
    """Get all actions that require passkey verification."""
    from ..services.webauthn_provider import get_webauthn_provider

    webauthn = get_webauthn_provider()

    return {
        "actions": webauthn.get_high_risk_actions(),
        "count": len(webauthn.HIGH_RISK_ACTIONS),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOM Bridge Endpoints (AWI Session Integration)
# ─────────────────────────────────────────────────────────────────────────────


class DOMAttachRequest(BaseModel):
    """Request to attach DOM bridge to an AWI session."""

    session_id: str
    target_url: str | None = None


class DOMAttachResponse(BaseModel):
    """Response after attaching DOM bridge."""

    status: str
    session_id: str
    dom_session_id: str
    elements_count: int
    page_type: str


@router.post(
    "/dom/attach",
    response_model=DOMAttachResponse,
    summary="Attach DOM bridge to AWI session",
    description="Attach a Playwright DOM bridge to an existing AWI session for live browser automation.",
)
async def attach_dom_bridge(request: DOMAttachRequest):
    """
    Attach a Playwright DOM bridge to an existing AWI session.

    After attachment, all actions executed via POST /v1/awi/execute will
    be routed through the real browser via Playwright, enabling
    interaction with any human-facing website.

    This is the key to making AWI work with existing websites:
    - Agent sends semantic action (e.g., "search_and_sort")
    - Bridge translates to real DOM commands
    - Browser executes the commands
    - Bridge extracts resulting state as AWI representation
    """
    from ..services.awi_session import get_awi_session_manager

    manager = get_awi_session_manager()

    try:
        result = await manager.attach_dom_bridge(
            session_id=request.session_id,
            target_url=request.target_url,
        )
        return DOMAttachResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "session_not_found", "message": str(e)},
        )
    except Exception as e:
        logger.exception(f"Failed to attach DOM bridge: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "attachment_failed", "message": str(e)},
        )


@router.delete(
    "/dom/attach/{session_id}",
    summary="Detach DOM bridge from AWI session",
)
async def detach_dom_bridge(session_id: str):
    """
    Detach the Playwright DOM bridge from an AWI session.

    Returns the session to mock/internal AWI mode. The browser context is closed.
    """
    from ..services.awi_session import get_awi_session_manager

    manager = get_awi_session_manager()

    try:
        result = await manager.detach_dom_bridge(session_id)
        return result
    except Exception as e:
        logger.exception(f"Failed to detach DOM bridge: {session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "detachment_failed", "message": str(e)},
        )


@router.get(
    "/dom/attach/{session_id}/status",
    summary="Get DOM bridge status",
)
async def get_dom_bridge_status(session_id: str):
    """
    Check if a session has a DOM bridge attached.
    """
    from ..services.awi_session import get_awi_session_manager

    manager = get_awi_session_manager()

    status = await manager.get_dom_bridge_status(session_id)
    return status


@router.post(
    "/dom/session",
    response_model=DOMBridgeSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create DOM bridge session",
    description="Create a browser session for bidirectional DOM translation.",
)
async def create_dom_session(request: DOMBridgeSessionRequest):
    """
    Create a new Playwright bridge session.

    The session opens a headless browser and navigates to the target URL.
    Use the returned session_id for subsequent DOM operations.
    """
    from ..services.awi_playwright_bridge import get_playwright_bridge

    bridge = get_playwright_bridge()

    try:
        session = await bridge.create_session(
            target_url=request.target_url,
            headless=request.headless,
            viewport=(request.viewport_width, request.viewport_height),
        )
        return DOMBridgeSessionResponse(
            session_id=session.session_id,
            current_url=session.current_url or request.target_url,
        )
    except Exception as e:
        logger.exception("Failed to create DOM session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "session_creation_failed", "message": str(e)},
        )


@router.delete(
    "/dom/session/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Destroy DOM bridge session",
)
async def destroy_dom_session(session_id: str):
    """Destroy a Playwright bridge session and cleanup resources."""
    from ..services.awi_playwright_bridge import get_playwright_bridge

    bridge = get_playwright_bridge()

    destroyed = await bridge.destroy_session(session_id)

    if not destroyed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Session {session_id} not found"},
        )


@router.get(
    "/dom/sessions",
    summary="List DOM sessions",
    description="List all active DOM bridge sessions.",
)
async def list_dom_sessions():
    """List all active DOM bridge sessions."""
    from ..services.awi_playwright_bridge import get_playwright_bridge

    bridge = get_playwright_bridge()

    sessions = await bridge.list_sessions()

    return {
        "sessions": sessions,
        "count": len(sessions),
    }


@router.post(
    "/dom/sync",
    response_model=DOMSyncResponse,
    summary="Execute AWI action via DOM",
    description="Execute an AWI action against real browser DOM via Playwright.",
)
async def sync_dom(request: DOMSyncRequest):
    """
    Bidirectional AWI ↔ DOM translation.

    Translates the AWI action to Playwright commands, executes them,
    and returns the resulting state representation.
    """
    from ..services.awi_playwright_bridge import get_playwright_bridge

    bridge = get_playwright_bridge()

    try:
        commands = await bridge.translate_action(
            session_id=request.session_id,
            action=request.action,
            parameters=request.parameters,
        )

        execution = await bridge.execute_commands(
            session_id=request.session_id,
            commands=commands,
        )

        representation = await bridge.extract_state_representation(
            session_id=request.session_id,
            representation_type="summary",
            include_elements=True,
        )

        return DOMSyncResponse(
            session_id=request.session_id,
            execution_id=str(uuid4()),
            action=request.action,
            commands_generated=len(commands),
            commands_executed=execution.commands_executed,
            new_url=execution.new_url,
            state_representation=representation,
            error=execution.error,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "translation_failed", "message": str(e)},
        )
    except Exception as e:
        logger.exception(f"DOM sync failed: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "execution_failed", "message": str(e)},
        )


@router.get(
    "/dom/state/{session_id}",
    response_model=DOMStateResponse,
    summary="Get DOM state representation",
    description="Get current state of the DOM as an AWI representation.",
)
async def get_dom_state(
    session_id: str,
    representation_type: DOMRepresentationType = DOMRepresentationType.SUMMARY,
):
    """Get current DOM state as AWI representation."""
    from ..services.awi_playwright_bridge import get_playwright_bridge

    bridge = get_playwright_bridge()

    session = await bridge.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Session {session_id} not found"},
        )

    try:
        state = await bridge.extract_state_representation(
            session_id=session_id,
            representation_type=representation_type.value,
            include_elements=True,
        )

        return DOMStateResponse(
            session_id=session_id,
            url=state.get("url", ""),
            title=state.get("title", ""),
            representation_type=representation_type,
            page_type=state.get("page_type", "generic"),
            main_content=state.get("main_content", ""),
            interactive_elements=[],
            forms=state.get("forms", []),
            navigation=state.get("navigation", []),
        )

    except Exception as e:
        logger.exception(f"DOM state extraction failed: {session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "extraction_failed", "message": str(e)},
        )


@router.post(
    "/dom/preview",
    summary="Preview AWI action translation",
    description="Preview what commands will be generated for an action.",
)
async def preview_action(request: DOMSyncRequest):
    """Preview commands without executing them."""
    from ..services.awi_playwright_bridge import get_playwright_bridge

    bridge = get_playwright_bridge()

    try:
        preview = await bridge.preview_action(
            session_id=request.session_id,
            action=request.action,
            parameters=request.parameters,
        )
        return preview
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "preview_failed", "message": str(e)},
        )
    except Exception as e:
        logger.exception(f"Action preview failed: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "preview_error", "message": str(e)},
        )


# ─────────────────────────────────────────────────────────────────────────────
# RAG Memory Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/rag/index",
    response_model=MemoryIndexResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Index AWI session",
    description="Index a completed AWI session for future retrieval.",
)
async def index_session(request: MemoryIndexRequest):
    """
    Index an AWI session for semantic search.

    Extracts entities, infers intent, and generates embeddings for retrieval.
    """
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    try:
        memory_id = await rag.index_session(
            session_id=request.session_id,
            session_type=request.session_type,
            action_history=request.action_history,
            state_snapshots=request.state_snapshots,
            metadata=request.metadata,
        )

        memory = await rag.get_memory(memory_id)

        return MemoryIndexResponse(
            memory_id=memory_id,
            session_id=request.session_id,
            indexed_at=memory.created_at if memory else datetime.utcnow(),
            entities_extracted=len(memory.key_entities) if memory else 0,
            intent_inferred=memory.user_intent if memory else "",
        )

    except Exception as e:
        logger.exception(f"Failed to index session: {request.session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "indexing_failed", "message": str(e)},
        )


@router.post(
    "/rag/query",
    response_model=RAGQueryResponse,
    summary="Query session memories",
    description="Semantic search over past AWI session memories.",
)
async def query_memories(request: RAGQueryRequest):
    """
    Query session memories with natural language.

    Returns relevant past sessions sorted by similarity to the query.
    """
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    try:
        start_time = datetime.utcnow()

        results = await rag.search(
            query=request.query,
            session_type=request.session_type,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            include_raw_state=request.include_raw_state,
        )

        search_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        return RAGQueryResponse(
            query=request.query,
            results=[
                {
                    "memory_id": r.memory_id,
                    "session_id": r.session_id,
                    "session_type": r.session_type,
                    "user_intent": r.user_intent,
                    "action_sequence": r.action_sequence,
                    "key_entities": r.key_entities,
                    "similarity_score": r.similarity_score,
                    "created_at": r.created_at,
                    "accessed_at": r.accessed_at,
                    "access_count": r.access_count,
                    "raw_state": r.raw_state,
                }
                for r in results
            ],
            total_found=len(results),
            search_time_ms=search_time_ms,
        )

    except Exception as e:
        logger.exception("RAG query failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "query_failed", "message": str(e)},
        )


@router.get(
    "/rag/memory/{memory_id}",
    summary="Get memory details",
    description="Get detailed information about a specific memory.",
)
async def get_memory(memory_id: str):
    """Get a specific memory by ID."""
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    memory = await rag.get_memory(memory_id)

    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Memory {memory_id} not found"},
        )

    return {
        "memory_id": memory.memory_id,
        "session_id": memory.session_id,
        "session_type": memory.session_type,
        "user_intent": memory.user_intent,
        "action_sequence": memory.action_sequence,
        "key_entities": memory.key_entities,
        "page_summaries": memory.page_summaries,
        "relevance_tags": memory.relevance_tags,
        "created_at": memory.created_at.isoformat(),
        "accessed_at": memory.accessed_at.isoformat(),
        "access_count": memory.access_count,
    }


@router.delete(
    "/rag/memory/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete memory",
    description="Delete a memory from the index.",
)
async def delete_memory(memory_id: str):
    """Delete a specific memory."""
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    deleted = await rag.delete_memory(memory_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Memory {memory_id} not found"},
        )


@router.get(
    "/rag/context/{session_id}",
    response_model=SessionContextResponse,
    summary="Get session context",
    description="Get relevant context from past sessions for the current session.",
)
async def get_session_context(
    session_id: str,
    session_type: str | None = None,
    top_k: int = 3,
):
    """
    Get relevant context from past sessions.

    Returns similar past sessions and suggested next actions to help
    the agent make informed decisions.
    """
    from ..services.awi_rag_engine import get_awi_rag_engine
    from ..services.awi_session import get_awi_session_manager

    rag = get_awi_rag_engine()
    session_manager = get_awi_session_manager()

    session = await session_manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Session {session_id} not found"},
        )

    try:
        current_state = {
            "url": session.target_url,
            "goal": "",
        }

        context = await rag.get_session_context(
            current_session_id=session_id,
            current_state=current_state,
            session_type=session_type,
            top_k=top_k,
        )

        return SessionContextResponse(**context)

    except Exception as e:
        logger.exception(f"Context retrieval failed: {session_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "context_failed", "message": str(e)},
        )


@router.get(
    "/rag/stats",
    summary="Get RAG statistics",
    description="Get statistics about the memory store.",
)
async def get_rag_stats():
    """Get statistics about indexed memories."""
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    stats = await rag.get_stats()

    return stats


@router.get(
    "/rag/sessions/{session_id}/memories",
    summary="Get session memories",
    description="Get all indexed memories for a session.",
)
async def get_session_memories(session_id: str):
    """Get all memories for a specific session."""
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    memories = await rag.get_session_memories(session_id)

    return {
        "session_id": session_id,
        "memories": [
            {
                "memory_id": m.memory_id,
                "session_type": m.session_type,
                "user_intent": m.user_intent,
                "action_count": len(m.action_sequence),
                "entity_count": len(m.key_entities),
                "created_at": m.created_at.isoformat(),
            }
            for m in memories
        ],
        "count": len(memories),
    }


@router.delete(
    "/rag/sessions/{session_id}/memories",
    summary="Delete session memories",
    description="Delete all memories for a session.",
)
async def delete_session_memories(session_id: str):
    """Delete all memories for a specific session."""
    from ..services.awi_rag_engine import get_awi_rag_engine

    rag = get_awi_rag_engine()

    deleted = await rag.delete_session_memories(session_id)

    return {
        "session_id": session_id,
        "deleted_count": deleted,
    }
