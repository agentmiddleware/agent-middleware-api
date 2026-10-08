"""Mock versus live disclosure for AWI sessions.

Covers the go-to-market finding that unattached (mock) execute results were
indistinguishable from live browser results: every mock payload now carries
an explicit simulated marker, dry_run previews instead of erroring, and the
RAG stats endpoint discloses hash based embeddings.
"""

import pytest

from app.schemas.awi import (
    AWIExecutionRequest,
    AWIRepresentationType,
    AWISessionCreate,
    AWIStandardAction,
)
from app.services.awi_rag_engine import AWIRAGEngine
from app.services.awi_representation import get_awi_representation
from app.services.awi_session import AWISessionManager


@pytest.mark.proof
@pytest.mark.anyio
async def test_unattached_execute_result_is_marked_simulated():
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.test")
    )
    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
        )
    )
    assert response.status == "success"
    assert response.result["simulated"] is True


@pytest.mark.proof
@pytest.mark.anyio
async def test_initial_page_state_is_marked_simulated():
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.test")
    )
    state = manager._session_state[session.session_id]
    assert state["page_state"]["simulated"] is True


@pytest.mark.proof
@pytest.mark.anyio
async def test_mock_navigate_refreshes_page_state_but_stays_simulated():
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.test")
    )
    await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
        )
    )
    state = manager._session_state[session.session_id]
    assert state["page_state"]["url"] == "https://example.test/next"
    assert state["page_state"]["simulated"] is True


@pytest.mark.proof
@pytest.mark.anyio
async def test_summary_of_simulated_page_state_says_so():
    engine = get_awi_representation()
    result = await engine.generate_representation(
        "test-session",
        AWIRepresentationType.SUMMARY,
        {"html": "<html><body>Initial page</body></html>", "simulated": True},
        {},
    )
    assert result["metadata"]["page_state_simulated"] is True


@pytest.mark.proof
@pytest.mark.anyio
async def test_live_page_state_is_not_flagged_simulated():
    engine = get_awi_representation()
    result = await engine.generate_representation(
        "test-session",
        AWIRepresentationType.SUMMARY,
        {"html": "<html><body>Real page</body></html>"},
        {},
    )
    assert result["metadata"]["page_state_simulated"] is False


@pytest.mark.proof
@pytest.mark.anyio
async def test_screenshot_placeholder_is_marked_simulated():
    engine = get_awi_representation()
    result = await engine.generate_representation(
        "test-session",
        AWIRepresentationType.LOW_RES_SCREENSHOT,
        {"html": "<html><body>Real page</body></html>"},
        {},
    )
    assert result["content"]["simulated"] is True
    assert "placeholder" in result["content"]


@pytest.mark.proof
@pytest.mark.anyio
async def test_dry_run_previews_without_mutation():
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.test")
    )
    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
            dry_run=True,
        )
    )
    assert response.status == "dry_run"
    assert response.effect_status == "not_dispatched"
    assert response.result["would_execute"] is True
    assert response.result["via"] == "mock"
    assert response.result["simulated"] is True
    assert session.step_count == 0
    assert session.action_history == []
    state = manager._session_state[session.session_id]
    assert state["current_url"] == "https://example.test"


@pytest.mark.proof
@pytest.mark.anyio
async def test_dry_run_reports_invalid_parameters():
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.test")
    )
    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={},
            dry_run=True,
        )
    )
    assert response.status == "error"
    assert response.effect_status == "not_dispatched"
    assert "Missing required parameter" in (response.error or "")
    assert session.step_count == 0


@pytest.mark.proof
@pytest.mark.anyio
async def test_dry_run_missing_session_stays_not_dispatched():
    manager = AWISessionManager()
    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id="awi-missing",
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test"},
            dry_run=True,
        )
    )
    assert response.status == "error"
    assert response.effect_status == "not_dispatched"


@pytest.mark.proof
@pytest.mark.anyio
async def test_dom_bridge_status_reports_mock_liveness():
    manager = AWISessionManager()
    session = await manager.create_session(
        AWISessionCreate(target_url="https://example.test")
    )
    assert (await manager.get_dom_bridge_status(session.session_id))[
        "attached"
    ] is False

    from types import SimpleNamespace

    from app.core.time import utc_now

    dom_session_id = "dom-synthetic"
    manager._dom_sessions[session.session_id] = dom_session_id
    manager._playwright_bridge._sessions[dom_session_id] = SimpleNamespace(
        session_id=dom_session_id,
        current_url="https://example.test",
        created_at=utc_now(),
        last_activity=utc_now(),
        _page=None,
    )
    try:
        status = await manager.get_dom_bridge_status(session.session_id)
    finally:
        manager._playwright_bridge._sessions.pop(dom_session_id, None)
    assert status["attached"] is True
    assert status["live_browser"] is False


@pytest.mark.proof
@pytest.mark.anyio
async def test_rag_stats_discloses_simulated_embeddings():
    engine = AWIRAGEngine(embedding_model="mock-embedding")
    stats = await engine.get_stats()
    assert stats["embeddings_simulated"] is True
