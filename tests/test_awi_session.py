"""Focused tests for app/services/awi_session.py.

Covers the AWISessionManager lifecycle: create, get, execute, human
intervention, representation requests, destroy, expiry cleanup, and DOM
bridge attach/detach. All dependencies are local or mocked, so the file
stays fast with no network access.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.awi import (
    AWIExecutionRequest,
    AWIHumanIntervention,
    AWIRepresentationRequest,
    AWIRepresentationType,
    AWISessionCreate,
    AWISessionStatus,
    AWIStandardAction,
)
from app.services.awi_session import AWISessionManager


def _make_create(**overrides):
    params = {"target_url": "https://example.test"}
    params.update(overrides)
    return AWISessionCreate(**params)


@pytest.mark.anyio
async def test_create_session_sets_defaults_and_initial_state():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create(max_steps=50))

    assert session.session_id.startswith("awi-")
    assert session.target_url == "https://example.test"
    assert session.current_url == "https://example.test"
    assert session.status == AWISessionStatus.CREATED
    assert session.max_steps == 50
    assert session.step_count == 0

    state = manager._session_state[session.session_id]
    assert state["current_url"] == "https://example.test"
    assert "page_loaded" in state["capabilities"]

    fetched = await manager.get_session(session.session_id)
    assert fetched is not None
    assert fetched.session_id == session.session_id


@pytest.mark.anyio
async def test_get_session_unknown_id_returns_none():
    manager = AWISessionManager()
    assert await manager.get_session("awi-does-not-exist") is None


@pytest.mark.anyio
async def test_execute_navigate_updates_url_and_step_count():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())

    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
        )
    )

    assert response.status == "success"
    assert response.result == {
        "success": True,
        "new_url": "https://example.test/next",
    }
    stored = await manager.get_session(session.session_id)
    assert stored is not None
    assert stored.step_count == 1
    assert stored.current_url == "https://example.test/next"
    assert stored.status == AWISessionStatus.ACTIVE


@pytest.mark.anyio
async def test_execute_action_unknown_session_returns_not_dispatched():
    manager = AWISessionManager()
    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id="awi-missing",
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
        )
    )

    assert response.status == "error"
    assert response.effect_status == "not_dispatched"
    assert "awi-missing" in (response.error or "")


@pytest.mark.anyio
async def test_execute_action_invalid_params_returns_error():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())

    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.SEARCH_AND_SORT,
            parameters={},
        )
    )

    assert response.status == "error"
    assert response.effect_status == "not_dispatched"
    assert "query" in (response.error or "")
    stored = await manager.get_session(session.session_id)
    assert stored is not None
    assert stored.step_count == 0


@pytest.mark.anyio
async def test_dry_run_does_not_dispatch_or_advance_steps():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())

    response = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
            dry_run=True,
        )
    )

    assert response.status == "error"
    assert response.error == "dry_run_unsupported"
    assert response.effect_status == "not_dispatched"
    stored = await manager.get_session(session.session_id)
    assert stored is not None
    assert stored.step_count == 0


@pytest.mark.anyio
async def test_max_steps_reached_after_limit():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create(max_steps=1))

    first = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/one"},
        )
    )
    assert first.status == "success"

    second = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/two"},
        )
    )

    assert second.status == "max_steps_reached"
    assert second.effect_status == "not_dispatched"
    stored = await manager.get_session(session.session_id)
    assert stored is not None
    assert stored.status == AWISessionStatus.COMPLETED
    assert stored.step_count == 1


@pytest.mark.anyio
async def test_paused_session_blocks_execution_until_resumed():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())

    paused = await manager.human_intervention(
        AWIHumanIntervention(
            session_id=session.session_id,
            action="pause",
            reason="operator review",
        )
    )
    assert paused == {"success": True, "status": "paused"}

    blocked = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
        )
    )
    assert blocked.status == "paused"
    assert blocked.effect_status == "not_dispatched"

    resumed = await manager.human_intervention(
        AWIHumanIntervention(session_id=session.session_id, action="resume")
    )
    assert resumed == {"success": True, "status": "active"}

    allowed = await manager.execute_action(
        AWIExecutionRequest(
            session_id=session.session_id,
            action=AWIStandardAction.NAVIGATE_TO,
            parameters={"url": "https://example.test/next"},
        )
    )
    assert allowed.status == "success"


@pytest.mark.anyio
async def test_human_intervention_edge_cases():
    manager = AWISessionManager()

    missing = await manager.human_intervention(
        AWIHumanIntervention(session_id="awi-missing", action="pause")
    )
    assert missing == {"success": False, "error": "Session not found"}

    session = await manager.create_session(_make_create())
    no_instructions = await manager.human_intervention(
        AWIHumanIntervention(session_id=session.session_id, action="steer")
    )
    assert no_instructions == {
        "success": False,
        "error": "No steering instructions provided",
    }

    unknown = await manager.human_intervention(
        AWIHumanIntervention(session_id=session.session_id, action="nonsense")
    )
    assert unknown == {"success": False, "error": "Unknown action: nonsense"}

    steered = await manager.human_intervention(
        AWIHumanIntervention(
            session_id=session.session_id,
            action="steer",
            steer_instructions="Focus on prices",
        )
    )
    assert steered["success"] is True
    assert steered["status"] == "steered"
    assert "instructions_sha256" in steered


@pytest.mark.anyio
async def test_request_representation_unknown_session_returns_none():
    manager = AWISessionManager()
    result = await manager.request_representation(
        AWIRepresentationRequest(
            session_id="awi-missing",
            representation_type=AWIRepresentationType.SUMMARY,
        )
    )
    assert result is None


@pytest.mark.anyio
async def test_request_representation_success_appends_history():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())

    response = await manager.request_representation(
        AWIRepresentationRequest(
            session_id=session.session_id,
            representation_type=AWIRepresentationType.SUMMARY,
        )
    )

    assert response is not None
    assert response.session_id == session.session_id
    assert response.representation_type == AWIRepresentationType.SUMMARY
    stored = await manager.get_session(session.session_id)
    assert stored is not None
    assert len(stored.representation_history) == 1


@pytest.mark.anyio
async def test_destroy_session_removes_state():
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())

    assert await manager.destroy_session(session.session_id) is True
    assert await manager.get_session(session.session_id) is None
    assert session.session_id not in manager._session_state
    assert await manager.destroy_session(session.session_id) is False


@pytest.mark.anyio
async def test_cleanup_expired_removes_only_expired_sessions():
    manager = AWISessionManager()
    fresh = await manager.create_session(_make_create())
    expired = await manager.create_session(_make_create())
    expired.updated_at = datetime.now(timezone.utc) - timedelta(
        seconds=expired.timeout_seconds + 60
    )

    result = manager.cleanup_expired()

    assert result == {"sessions_removed": 1}
    assert expired.session_id not in manager._sessions
    assert fresh.session_id in manager._sessions


@pytest.mark.anyio
async def test_attach_and_detach_dom_bridge(monkeypatch):
    manager = AWISessionManager()
    session = await manager.create_session(_make_create())
    monkeypatch.setattr(
        manager._playwright_bridge,
        "create_session",
        AsyncMock(return_value=SimpleNamespace(session_id="dom-1")),
    )
    monkeypatch.setattr(
        manager._playwright_bridge,
        "extract_state_representation",
        AsyncMock(
            return_value={
                "interactive_elements": [{"id": "b1"}],
                "page_type": "test",
                "url": "https://example.test",
            }
        ),
    )
    monkeypatch.setattr(
        manager._playwright_bridge, "destroy_session", AsyncMock(return_value=True)
    )

    attached = await manager.attach_dom_bridge(session.session_id)

    assert attached["status"] == "attached"
    assert attached["dom_session_id"] == "dom-1"
    assert attached["elements_count"] == 1

    status = await manager.get_dom_bridge_status(session.session_id)
    assert status["attached"] is False  # real bridge store holds no dom-1 session

    detached = await manager.detach_dom_bridge(session.session_id)
    assert detached == {
        "status": "detached",
        "session_id": session.session_id,
        "dom_session_id": "dom-1",
    }

    again = await manager.detach_dom_bridge(session.session_id)
    assert again == {"status": "not_attached", "session_id": session.session_id}


@pytest.mark.anyio
async def test_attach_dom_bridge_unknown_session_raises():
    manager = AWISessionManager()
    with pytest.raises(ValueError, match="Session not found"):
        await manager.attach_dom_bridge("awi-missing")
