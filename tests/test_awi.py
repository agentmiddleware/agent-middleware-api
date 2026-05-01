"""
Tests for AWI (Agentic Web Interface) — Phase 7
=================================================
Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"
"""

import pytest

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.awi import (
    AWIActionCategory,
    AWISessionCreate,
    AWISessionStatus,
    AWIStandardAction,
    AWITaskCreate,
    AWITaskStatus,
    AWIRepresentationType,
    AWIHumanIntervention,
)
from app.services.awi_action_vocab import AWIActionVocabulary, get_awi_vocabulary
from app.services.awi_representation import get_awi_representation
from app.services.awi_task_queue import AWITaskQueue, get_awi_task_queue
from app.services.awi_session import AWISessionManager, get_awi_session_manager

HEADERS = {"X-API-Key": "test-key"}


class TestAWIActionVocabulary:
    """Test AWI action vocabulary."""

    def test_vocabulary_singleton(self):
        """Test vocabulary is singleton."""
        vocab1 = get_awi_vocabulary()
        vocab2 = get_awi_vocabulary()
        assert vocab1 is vocab2

    def test_list_all_actions(self):
        """Test listing all actions."""
        vocab = get_awi_vocabulary()
        actions = vocab.list_all_actions()
        assert len(actions) > 0
        assert all(hasattr(a, "action") for a in actions)

    def test_get_action(self):
        """Test getting a specific action."""
        vocab = get_awi_vocabulary()
        action = vocab.get_action(AWIStandardAction.SEARCH_AND_SORT)
        assert action is not None
        assert action.category == AWIActionCategory.SEARCH

    def test_list_by_category(self):
        """Test listing actions by category."""
        vocab = get_awi_vocabulary()
        actions = vocab.list_actions_by_category(AWIActionCategory.NAVIGATION)
        assert len(actions) > 0
        assert all(a.category == AWIActionCategory.NAVIGATION for a in actions)

    def test_validate_parameters_valid(self):
        """Test parameter validation with valid params."""
        vocab = get_awi_vocabulary()
        is_valid, error = vocab.validate_parameters(
            AWIStandardAction.SEARCH_AND_SORT, {"query": "laptops"}
        )
        assert is_valid is True
        assert error is None

    def test_validate_parameters_missing_required(self):
        """Test parameter validation with missing required params."""
        vocab = get_awi_vocabulary()
        is_valid, error = vocab.validate_parameters(
            AWIStandardAction.SEARCH_AND_SORT, {}
        )
        assert is_valid is False
        assert "query" in error

    def test_get_estimated_cost(self):
        """Test getting estimated cost for action."""
        vocab = get_awi_vocabulary()
        cost = vocab.get_estimated_cost(AWIStandardAction.CHECKOUT)
        assert cost > 0


class TestAWIRepresentation:
    """Test progressive representation engine."""

    @pytest.mark.anyio
    async def test_generate_summary(self):
        """Test generating summary representation."""
        engine = get_awi_representation()
        page_state = {
            "html": "<html><body><h1>Test</h1><p>Content here</p></body></html>",
            "title": "Test Page",
            "url": "https://example.com",
            "elements": [{"tag": "h1"}, {"tag": "p"}],
        }

        result = await engine.generate_representation(
            "test-session",
            AWIRepresentationType.SUMMARY,
            page_state,
            {"max_length": 100},
        )

        assert result["representation_type"] == "summary"
        assert "content" in result
        assert "metadata" in result

    @pytest.mark.anyio
    async def test_generate_embedding(self):
        """Test generating embedding representation."""
        engine = get_awi_representation()
        page_state = {
            "html": "<html><body>Test content</body></html>",
            "title": "Test",
            "url": "https://example.com",
        }

        result = await engine.generate_representation(
            "test-session", AWIRepresentationType.EMBEDDING, page_state, {}
        )

        assert result["representation_type"] == "embedding"
        assert "vector" in result["content"]


class TestAWITaskQueue:
    """Test AWI task queue."""

    @pytest.mark.anyio
    async def test_create_task(self):
        """Test creating a task."""
        queue = AWITaskQueue(max_concurrent_tasks=5)
        request = AWITaskCreate(
            task_type="web_scraping",
            target_url="https://example.com",
            action_sequence=[{"action": "navigate_to"}],
            priority=3,
        )

        task = await queue.create_task(request)

        assert task.task_id.startswith("awi-task-")
        assert task.task_type == "web_scraping"
        assert task.status == AWITaskStatus.PENDING
        assert task.priority == 3

    @pytest.mark.anyio
    async def test_priority_queue_ordering(self):
        """Test tasks are ordered by priority."""
        queue = AWITaskQueue()

        task1 = await queue.create_task(
            AWITaskCreate(
                task_type="low",
                target_url="https://example.com",
                action_sequence=[],
                priority=5,
            )
        )
        task2 = await queue.create_task(
            AWITaskCreate(
                task_type="high",
                target_url="https://example.com",
                action_sequence=[],
                priority=1,
            )
        )
        task3 = await queue.create_task(
            AWITaskCreate(
                task_type="medium",
                target_url="https://example.com",
                action_sequence=[],
                priority=3,
            )
        )

        assert queue._pending_queue[0] == task2.task_id
        assert queue._pending_queue[1] == task3.task_id
        assert queue._pending_queue[2] == task1.task_id

    @pytest.mark.anyio
    async def test_global_pause_resume(self):
        """Test global pause and resume."""
        queue = AWITaskQueue()

        await queue.global_pause("Human review needed")
        is_paused, reason = queue.is_global_paused()

        assert is_paused is True
        assert reason == "Human review needed"

        await queue.global_resume()
        is_paused, _ = queue.is_global_paused()

        assert is_paused is False


class TestAWISessionManager:
    """Test AWI session manager."""

    @pytest.mark.anyio
    async def test_create_session(self):
        """Test creating an AWI session."""
        manager = AWISessionManager()
        request = AWISessionCreate(
            target_url="https://example.com",
            max_steps=50,
        )

        session = await manager.create_session(request)

        assert session.session_id.startswith("awi-")
        assert session.target_url == "https://example.com"
        assert session.status == AWISessionStatus.CREATED
        assert session.max_steps == 50

    @pytest.mark.anyio
    async def test_execute_action(self):
        """Test executing an action in a session."""
        manager = AWISessionManager()
        session = await manager.create_session(
            AWISessionCreate(
                target_url="https://example.com",
            )
        )

        from app.schemas.awi import AWIExecutionRequest

        result = await manager.execute_action(
            AWIExecutionRequest(
                session_id=session.session_id,
                action=AWIStandardAction.NAVIGATE_TO,
                parameters={"url": "https://new-page.com"},
            )
        )

        assert result.status == "success"
        assert result.action == AWIStandardAction.NAVIGATE_TO

    @pytest.mark.anyio
    async def test_human_intervention_pause(self):
        """Test human intervention to pause session."""
        manager = AWISessionManager()
        session = await manager.create_session(
            AWISessionCreate(
                target_url="https://example.com",
            )
        )

        result = await manager.human_intervention(
            AWIHumanIntervention(
                session_id=session.session_id,
                action="pause",
                reason="Human review",
            )
        )

        assert result["success"] is True
        assert result["status"] == "paused"

    @pytest.mark.anyio
    async def test_human_intervention_steer(self):
        """Test human steering a session."""
        manager = AWISessionManager()
        session = await manager.create_session(
            AWISessionCreate(
                target_url="https://example.com",
            )
        )
        await manager.human_intervention(
            AWIHumanIntervention(
                session_id=session.session_id,
                action="pause",
            )
        )

        result = await manager.human_intervention(
            AWIHumanIntervention(
                session_id=session.session_id,
                action="steer",
                steer_instructions="Focus on product prices",
            )
        )

        assert result["success"] is True
        assert "instructions_recorded" in result


class TestAWIRouter:
    """Test AWI router endpoints."""

    @pytest.mark.anyio
    async def test_create_session_endpoint(self):
        """Test POST /v1/awi/sessions."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/awi/sessions",
                json={
                    "target_url": "https://example.com",
                    "max_steps": 100,
                },
                headers=HEADERS,
            )

            assert response.status_code == 201
            data = response.json()
            assert "session_id" in data
            assert data["target_url"] == "https://example.com"

    @pytest.mark.anyio
    async def test_get_session_endpoint(self):
        """Test GET /v1/awi/sessions/{session_id}."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_response = await client.post(
                "/v1/awi/sessions",
                json={"target_url": "https://example.com"},
                headers=HEADERS,
            )
            session_id = create_response.json()["session_id"]

            response = await client.get(
                f"/v1/awi/sessions/{session_id}", headers=HEADERS
            )

            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == session_id

    @pytest.mark.anyio
    async def test_execute_action_endpoint(self):
        """Test POST /v1/awi/execute."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_response = await client.post(
                "/v1/awi/sessions",
                json={"target_url": "https://example.com"},
                headers=HEADERS,
            )
            session_id = create_response.json()["session_id"]

            response = await client.post(
                "/v1/awi/execute",
                json={
                    "session_id": session_id,
                    "action": "navigate_to",
                    "parameters": {"url": "https://new-page.com"},
                },
                headers=HEADERS,
            )

            assert response.status_code == 200
            data = response.json()
            assert "execution_id" in data
            assert data["status"] == "success"

    @pytest.mark.anyio
    async def test_list_vocabulary_endpoint(self):
        """Test GET /v1/awi/vocabulary."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/awi/vocabulary")

            assert response.status_code == 200
            data = response.json()
            assert "actions" in data
            assert len(data["actions"]) > 0

    @pytest.mark.anyio
    async def test_create_task_endpoint(self):
        """Test POST /v1/awi/tasks."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/awi/tasks",
                json={
                    "task_type": "automation",
                    "target_url": "https://example.com",
                    "action_sequence": [{"action": "navigate_to"}],
                    "priority": 5,
                },
                headers=HEADERS,
            )

            assert response.status_code == 201
            data = response.json()
            assert "task_id" in data
            assert data["task_type"] == "automation"

    @pytest.mark.anyio
    async def test_queue_status_endpoint(self):
        """Test GET /v1/awi/queue/status."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/awi/queue/status", headers=HEADERS)

            assert response.status_code == 200
            data = response.json()
            assert "total_pending" in data
            assert "total_running" in data

    @pytest.mark.anyio
    async def test_session_endpoints_require_api_key(self):
        """AWI session control is not publicly reachable."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/awi/sessions",
                json={"target_url": "https://example.com"},
            )

            assert response.status_code == 401

    @pytest.mark.anyio
    async def test_db_key_is_scoped_to_awi_session_wallet(self):
        """DB API keys can only drive AWI sessions for their issuing wallet."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            wallet_a_resp = await client.post(
                "/v1/billing/wallets/sponsor",
                json={"sponsor_name": "AWI Tenant A", "email": "awi-a@test.com"},
                headers=HEADERS,
            )
            wallet_b_resp = await client.post(
                "/v1/billing/wallets/sponsor",
                json={"sponsor_name": "AWI Tenant B", "email": "awi-b@test.com"},
                headers=HEADERS,
            )
            wallet_a = wallet_a_resp.json()["wallet_id"]
            wallet_b = wallet_b_resp.json()["wallet_id"]

            key_resp = await client.post(
                "/v1/api-keys",
                json={"wallet_id": wallet_a, "key_name": "awi-tenant-key"},
                headers=HEADERS,
            )
            db_headers = {"X-API-Key": key_resp.json()["api_key"]}

            own_session_resp = await client.post(
                "/v1/awi/sessions",
                json={"target_url": "https://example.com", "wallet_id": wallet_a},
                headers=db_headers,
            )
            assert own_session_resp.status_code == 201
            own_session_id = own_session_resp.json()["session_id"]

            own_get = await client.get(
                f"/v1/awi/sessions/{own_session_id}", headers=db_headers
            )
            assert own_get.status_code == 200

            other_session_resp = await client.post(
                "/v1/awi/sessions",
                json={"target_url": "https://example.com", "wallet_id": wallet_b},
                headers=HEADERS,
            )
            other_session_id = other_session_resp.json()["session_id"]

            blocked_get = await client.get(
                f"/v1/awi/sessions/{other_session_id}", headers=db_headers
            )
            blocked_execute = await client.post(
                "/v1/awi/execute",
                json={
                    "session_id": other_session_id,
                    "action": "navigate_to",
                    "parameters": {"url": "https://blocked.example.com"},
                },
                headers=db_headers,
            )

            assert blocked_get.status_code == 403
            assert blocked_execute.status_code == 403

    @pytest.mark.anyio
    async def test_passkey_challenge_requires_session_owner(self):
        """Login-window passkey challenges inherit AWI session ownership."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            wallet_resp = await client.post(
                "/v1/billing/wallets/sponsor",
                json={"sponsor_name": "AWI Passkey", "email": "awi-passkey@test.com"},
                headers=HEADERS,
            )
            wallet_id = wallet_resp.json()["wallet_id"]
            session_resp = await client.post(
                "/v1/awi/sessions",
                json={"target_url": "https://example.com", "wallet_id": wallet_id},
                headers=HEADERS,
            )
            session_id = session_resp.json()["session_id"]

            no_auth = await client.post(
                "/v1/awi/passkey/challenge",
                json={"session_id": session_id, "action": "checkout"},
            )
            with_auth = await client.post(
                "/v1/awi/passkey/challenge",
                json={"session_id": session_id, "action": "checkout"},
                headers=HEADERS,
            )

            assert no_auth.status_code == 401
            assert with_auth.status_code == 200
