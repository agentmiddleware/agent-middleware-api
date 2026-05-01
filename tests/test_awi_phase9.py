"""
Tests for Phase 9 AWI Enhanced Features
======================================

Tests for:
- WebAuthn/Passkey provider
- AWI Playwright bridge
- AWI RAG engine
"""

import pytest
from datetime import datetime, timedelta

from app.services.webauthn_provider import WebAuthnProvider, ChallengeStatus
from app.services.awi_playwright_bridge import (
    AWIPlaywrightBridge,
    BrowserSessionLimitExceeded,
    PlaywrightCommand,
    CommandType,
    TranslationMode,
)
from app.services.awi_rag_engine import AWIRAGEngine, SearchResult


class TestWebAuthnProvider:
    """Tests for WebAuthn/Passkey provider."""

    @pytest.fixture
    def provider(self):
        return WebAuthnProvider(
            rp_id="test.example.com",
            rp_name="Test App",
            challenge_expiry_seconds=60,
            verification_validity_seconds=60,
        )

    def test_high_risk_actions_require_passkey(self, provider):
        """Test that high-risk actions require passkey verification."""
        high_risk = ["checkout", "payment", "delete_account", "transfer_funds"]

        for action in high_risk:
            assert provider.HIGH_RISK_ACTIONS is not None
            assert action.lower() in provider.HIGH_RISK_ACTIONS

    @pytest.mark.asyncio
    async def test_low_risk_actions_no_passkey(self, provider):
        """Test that low-risk actions don't require passkey."""
        low_risk = ["navigate_to", "scroll", "search_and_sort"]

        for action in low_risk:
            result = await provider.requires_passkey("session1", action)
            assert result is False

    @pytest.mark.asyncio
    async def test_requires_passkey_returns_true_for_high_risk(self, provider):
        """Test requires_passkey for high-risk actions."""
        result = await provider.requires_passkey("session1", "checkout")
        assert result is True

    @pytest.mark.asyncio
    async def test_requires_passkey_returns_false_for_low_risk(self, provider):
        """Test requires_passkey for low-risk actions."""
        result = await provider.requires_passkey("session1", "navigate_to")
        assert result is False

    @pytest.mark.asyncio
    async def test_create_challenge(self, provider):
        """Test challenge creation."""
        challenge = await provider.create_challenge(
            session_id="session1",
            action="checkout",
        )

        assert challenge["challenge_id"] is not None
        assert challenge["rp_id"] == "test.example.com"
        assert challenge["rp_name"] == "Test App"
        assert challenge["timeout"] == 60000
        assert "challenge" in challenge
        assert "public_key_cred_params" in challenge

    @pytest.mark.asyncio
    async def test_create_challenge_fails_for_low_risk_action(self, provider):
        """Test that challenge creation fails for low-risk actions."""
        with pytest.raises(ValueError) as exc_info:
            await provider.create_challenge(
                session_id="session1",
                action="navigate_to",
            )

        assert "does not require passkey" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_verify_response_invalid_challenge(self, provider):
        """Test verification with invalid challenge ID."""
        with pytest.raises(ValueError) as exc_info:
            await provider.verify_response(
                challenge_id="invalid-id",
                credential={},
            )

        assert "Challenge not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_verify_response_expired(self, provider):
        """Test verification with expired challenge."""
        provider._challenge_expiry = -1  # Always expired

        challenge = await provider.create_challenge(
            session_id="session1",
            action="checkout",
        )

        with pytest.raises(ValueError) as exc_info:
            await provider.verify_response(
                challenge_id=challenge["challenge_id"],
                credential={},
            )

        assert "expired" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_verify_response_success(self, provider):
        """Test successful verification."""
        challenge = await provider.create_challenge(
            session_id="session1",
            action="checkout",
        )

        # Mock credential with required fields
        credential = {
            "id": "test-credential-id",
            "raw_id": "test-raw-id",
            "type": "public-key",
            "response": {
                "authenticator_data": "dGVzdA==",
                "client_data_json": '{"type":"webauthn.get","challenge":"test","origin":"https://test.example.com"}',
                "signature": "dGVzdA==",
            },
        }

        result = await provider.verify_response(
            challenge_id=challenge["challenge_id"],
            credential=credential,
        )

        assert result["verified"] is True
        assert result["session_id"] == "session1"
        assert result["action"] == "checkout"
        assert "expires_in_seconds" in result

    @pytest.mark.asyncio
    async def test_is_action_verified_false_initially(self, provider):
        """Test that actions are not verified initially."""
        result = await provider.is_action_verified("session1", "checkout")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_action_verified_after_verification(self, provider):
        """Test that actions are verified after successful verification."""
        challenge = await provider.create_challenge(
            session_id="session1",
            action="checkout",
        )

        credential = {
            "id": "test-credential-id",
            "raw_id": "test-raw-id",
            "type": "public-key",
            "response": {
                "authenticator_data": "dGVzdA==",
                "client_data_json": '{"type":"webauthn.get","challenge":"test","origin":"https://test.example.com"}',
                "signature": "dGVzdA==",
            },
        }

        await provider.verify_response(
            challenge_id=challenge["challenge_id"],
            credential=credential,
        )

        result = await provider.is_action_verified("session1", "checkout")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_action_verified_false_for_different_action(self, provider):
        """Test that verification doesn't apply to different actions."""
        challenge = await provider.create_challenge(
            session_id="session1",
            action="checkout",
        )

        credential = {
            "id": "test-credential-id",
            "raw_id": "test-raw-id",
            "type": "public-key",
            "response": {
                "authenticator_data": "dGVzdA==",
                "client_data_json": '{"type":"webauthn.get","challenge":"test","origin":"https://test.example.com"}',
                "signature": "dGVzdA==",
            },
        }

        await provider.verify_response(
            challenge_id=challenge["challenge_id"],
            credential=credential,
        )

        result = await provider.is_action_verified("session1", "payment")
        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_verification(self, provider):
        """Test invalidating verification."""
        challenge = await provider.create_challenge(
            session_id="session1",
            action="checkout",
        )

        credential = {
            "id": "test-credential-id",
            "raw_id": "test-raw-id",
            "type": "public-key",
            "response": {
                "authenticator_data": "dGVzdA==",
                "client_data_json": '{"type":"webauthn.get","challenge":"test","origin":"https://test.example.com"}',
                "signature": "dGVzdA==",
            },
        }

        await provider.verify_response(
            challenge_id=challenge["challenge_id"],
            credential=credential,
        )

        invalidated = await provider.invalidate_verification("session1", "checkout")
        assert invalidated == 1

        result = await provider.is_action_verified("session1", "checkout")
        assert result is False

    def test_get_high_risk_actions(self, provider):
        """Test getting list of high-risk actions."""
        actions = provider.get_high_risk_actions()

        assert isinstance(actions, list)
        assert len(actions) > 0
        assert "checkout" in actions
        assert "payment" in actions

    def test_cleanup_expired(self, provider):
        """Test cleanup of expired challenges."""
        provider._challenge_expiry = 1

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            provider.create_challenge("session1", "checkout")
        )

        import time

        time.sleep(0.1)

        result = provider.cleanup_expired()

        assert "challenges_removed" in result
        assert "verifications_removed" in result


class TestAWIPlaywrightBridge:
    """Tests for AWI Playwright Bridge."""

    @pytest.fixture
    def bridge(self):
        return AWIPlaywrightBridge(mode=TranslationMode.CDP_DIRECT)

    def test_semantic_patterns_exist(self, bridge):
        """Test that semantic patterns are defined."""
        patterns = bridge.SEMANTIC_PATTERNS

        assert "search_input" in patterns
        assert "add_to_cart" in patterns
        assert "checkout" in patterns
        assert "password_input" in patterns

    def test_semantic_pattern_has_tags(self, bridge):
        """Test that semantic patterns have tags."""
        for semantic_type, pattern in bridge.SEMANTIC_PATTERNS.items():
            assert "tags" in pattern
            assert len(pattern["tags"]) > 0

    def test_sort_value_mappings_exist(self, bridge):
        """Test that sort value mappings are defined."""
        mappings = bridge.SORT_VALUE_MAPPINGS

        assert "price_low" in mappings
        assert "price_high" in mappings
        assert "relevance" in mappings

    @pytest.mark.asyncio
    async def test_create_session(self, bridge):
        """Test session creation."""
        session = await bridge.create_session("https://example.com")

        assert session.session_id is not None
        assert session.current_url == "https://example.com"
        assert session.created_at is not None

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_create_session_enforces_max_sessions(self):
        """DOM bridge refuses unbounded browser session creation."""
        bridge = AWIPlaywrightBridge(mode=TranslationMode.CDP_DIRECT, max_sessions=1)
        session = await bridge.create_session("https://example.com")

        with pytest.raises(BrowserSessionLimitExceeded):
            await bridge.create_session("https://example.org")

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_destroy_session(self, bridge):
        """Test session destruction."""
        session = await bridge.create_session("https://example.com")
        session_id = session.session_id

        result = await bridge.destroy_session(session_id)
        assert result is True

        result = await bridge.destroy_session("invalid-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_translate_search_and_sort(self, bridge):
        """Test translating search_and_sort action."""
        session = await bridge.create_session("https://example.com")

        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="search_and_sort",
            parameters={"query": "laptop", "sort_by": "price_low"},
        )

        assert isinstance(commands, list)

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_add_to_cart(self, bridge):
        """Test translating add_to_cart action."""
        session = await bridge.create_session("https://example.com")

        with pytest.raises(ValueError) as exc_info:
            await bridge.translate_action(
                session_id=session.session_id,
                action="add_to_cart",
                parameters={},
            )

        assert "No add-to-cart element found" in str(exc_info.value)

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_fill_form(self, bridge):
        """Test translating fill_form action."""
        session = await bridge.create_session("https://example.com")

        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="fill_form",
            parameters={
                "data": {
                    "email": "test@example.com",
                    "password": "secret123",
                }
            },
        )

        assert isinstance(commands, list)

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_login(self, bridge):
        """Test translating login action."""
        session = await bridge.create_session("https://example.com/login")

        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="login",
            parameters={"email": "test@example.com", "password": "secret"},
        )

        assert isinstance(commands, list)

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_navigate_to(self, bridge):
        """Test translating navigate_to action."""
        session = await bridge.create_session("https://example.com")

        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="navigate_to",
            parameters={"url": "https://example.com/shop"},
        )

        assert len(commands) == 1
        assert commands[0].command_type == CommandType.GOTO

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_scroll(self, bridge):
        """Test translating scroll action."""
        session = await bridge.create_session("https://example.com")

        commands = await bridge.translate_action(
            session_id=session.session_id,
            action="scroll",
            parameters={"direction": "down", "amount": 500},
        )

        assert len(commands) == 1
        assert commands[0].command_type == CommandType.EVALUATE

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_unsupported_action(self, bridge):
        """Test translating unsupported action."""
        session = await bridge.create_session("https://example.com")

        with pytest.raises(ValueError) as exc_info:
            await bridge.translate_action(
                session_id=session.session_id,
                action="unsupported_action",
                parameters={},
            )

        assert "Unsupported AWI action" in str(exc_info.value)

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_translate_invalid_session(self, bridge):
        """Test translating action with invalid session."""
        with pytest.raises(ValueError) as exc_info:
            await bridge.translate_action(
                session_id="invalid-session",
                action="search_and_sort",
                parameters={},
            )

        assert "Session invalid-session not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_commands(self, bridge):
        """Test command execution without opening a real browser."""

        class FakePage:
            url = "https://example.com"

            async def title(self):
                return "Example"

        session = await bridge.create_session("https://example.com")
        session._page = FakePage()

        commands = [
            PlaywrightCommand(
                command_type=CommandType.WAIT_FOR_TIMEOUT,
                target="",
                wait_for_timeout_ms=100,
            )
        ]

        result = await bridge.execute_commands(
            session_id=session.session_id,
            commands=commands,
        )

        assert result.success is True
        assert result.commands_executed == 1

        await bridge.destroy_session(session.session_id)

    @pytest.mark.asyncio
    async def test_extract_state_representation(self, bridge):
        """Test extracting state representation (skipped if Playwright not installed)."""
        # Check if Playwright is available
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            pytest.skip("Playwright not installed")

        session = await bridge.create_session("https://example.com")

        representation = await bridge.extract_state_representation(
            session_id=session.session_id,
            representation_type="summary",
        )

        assert "session_id" in representation
        assert "url" in representation
        assert "page_type" in representation

        await bridge.destroy_session(session.session_id)

    def test_classify_page_type(self, bridge):
        """Test page type classification."""
        from app.services.awi_playwright_bridge import BridgeSession

        # Shopping page
        session = BridgeSession(
            session_id="test", current_url="https://shop.example.com"
        )
        page_type = bridge._classify_page_type(session)
        assert page_type == "product_listing"

        # Login page
        session = BridgeSession(
            session_id="test", current_url="https://example.com/login"
        )
        page_type = bridge._classify_page_type(session)
        assert page_type == "login"

        # Generic page
        session = BridgeSession(session_id="test", current_url="https://example.com")
        page_type = bridge._classify_page_type(session)
        assert page_type == "generic"

    def test_infer_field_type(self, bridge):
        """Test field type inference."""
        assert bridge._infer_field_type("email", "test@example.com") == "email_input"
        assert bridge._infer_field_type("password", "secret") == "password_input"
        assert bridge._infer_field_type("search_box", "") == "search_input"
        assert bridge._infer_field_type("phone_number", "123") == "text_input"

    def test_get_sort_option_value(self, bridge):
        """Test sort option value mapping."""
        assert bridge._get_sort_option_value("price_low") == "price-asc"
        assert bridge._get_sort_option_value("price_high") == "price-desc"
        assert bridge._get_sort_option_value("relevance") == "relevance"


class TestAWIRAGEngine:
    """Tests for AWI RAG Engine."""

    @pytest.fixture
    def engine(self):
        return AWIRAGEngine(embedding_dimension=32)

    @pytest.mark.asyncio
    async def test_index_session(self, engine):
        """Test session indexing."""
        memory_id = await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[
                {"action": "search_and_sort", "parameters": {"query": "laptop"}},
                {"action": "add_to_cart", "parameters": {"product": "ThinkPad X1"}},
            ],
            state_snapshots=[
                {"summary": "Product listing page", "page_type": "product_listing"},
            ],
        )

        assert memory_id is not None

        memory = await engine.get_memory(memory_id)
        assert memory is not None
        assert memory.session_type == "shopping"
        assert memory.session_id == "session1"

    @pytest.mark.asyncio
    async def test_search(self, engine):
        """Test semantic search."""
        await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[
                {"action": "search_and_sort", "parameters": {"query": "laptop"}},
            ],
            state_snapshots=[
                {"summary": "Product listing page", "page_type": "shopping"},
            ],
        )

        results = await engine.search(
            query="shopping for laptops",
            top_k=5,
            similarity_threshold=0.0,
        )

        assert len(results) > 0
        assert results[0].session_type == "shopping"

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, engine):
        """Test search with session type filter."""
        await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[{"action": "search"}],
            state_snapshots=[],
        )

        await engine.index_session(
            session_id="session2",
            session_type="form_filling",
            action_history=[{"action": "fill_form"}],
            state_snapshots=[],
        )

        results = await engine.search(
            query="task",
            session_type="shopping",
            top_k=5,
            similarity_threshold=0.0,
        )

        assert all(r.session_type == "shopping" for r in results)

    @pytest.mark.asyncio
    async def test_search_by_entities(self, engine):
        """Test entity-based search."""
        await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[],
            state_snapshots=[],
        )

        results = await engine.search_by_entities(
            entities=["ThinkPad", "MacBook"],
            top_k=5,
        )

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_session_context(self, engine):
        """Test getting session context."""
        await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[
                {"action": "search_and_sort"},
                {"action": "add_to_cart"},
                {"action": "checkout"},
            ],
            state_snapshots=[],
        )

        context = await engine.get_session_context(
            current_session_id="session2",
            current_state={"url": "https://shop.example.com", "goal": "buy laptop"},
            top_k=3,
        )

        assert "current_session_type" in context
        assert "suggested_next_actions" in context

    @pytest.mark.asyncio
    async def test_delete_memory(self, engine):
        """Test memory deletion."""
        memory_id = await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[],
            state_snapshots=[],
        )

        result = await engine.delete_memory(memory_id)
        assert result is True

        memory = await engine.get_memory(memory_id)
        assert memory is None

    @pytest.mark.asyncio
    async def test_delete_memory_not_found(self, engine):
        """Test deleting non-existent memory."""
        result = await engine.delete_memory("non-existent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_stats(self, engine):
        """Test getting statistics."""
        await engine.index_session(
            session_id="session1",
            session_type="shopping",
            action_history=[],
            state_snapshots=[],
        )

        await engine.index_session(
            session_id="session2",
            session_type="form_filling",
            action_history=[],
            state_snapshots=[],
        )

        stats = await engine.get_stats()

        assert stats["total_memories"] >= 2
        assert stats["total_sessions"] >= 2
        assert "type_counts" in stats

    def test_infer_session_type(self, engine):
        """Test session type inference."""
        # Shopping
        result = engine._infer_session_type(
            "generic",
            ["search_and_sort", "add_to_cart", "checkout"],
            [{"page_type": "shopping"}],
        )
        assert result == "shopping"

        # Form filling
        result = engine._infer_session_type(
            "generic",
            ["fill_form"],
            [{"page_type": "form"}],
        )
        assert result == "form_filling"

        # Login
        result = engine._infer_session_type(
            "generic",
            ["login"],
            [{"page_type": "login"}],
        )
        assert result == "authentication"

    def test_cosine_similarity(self, engine):
        """Test cosine similarity calculation."""
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert engine._cosine_similarity(a, b) == pytest.approx(1.0)

        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert engine._cosine_similarity(a, b) == pytest.approx(0.0)

        a = [1.0, 1.0]
        b = [1.0, 1.0]
        assert engine._cosine_similarity(a, b) == pytest.approx(1.0)

    def test_extract_entities(self, engine):
        """Test entity extraction."""
        action_history = [
            {"action": "add_to_cart", "parameters": {"product": "ThinkPad X1"}},
            {"action": "add_to_cart", "parameters": {"product": "MacBook Pro"}},
        ]

        entities = engine._extract_entities(action_history, [])

        assert "ThinkPad X1" in entities
        assert "MacBook Pro" in entities

    def test_suggest_actions(self, engine):
        """Test action suggestion."""
        similar_sessions = [
            SearchResult(
                memory_id="m1",
                session_id="s1",
                session_type="shopping",
                user_intent="buy laptop",
                action_sequence=["search", "add_to_cart", "checkout"],
                key_entities=[],
                similarity_score=0.9,
                created_at=datetime.utcnow(),
                accessed_at=datetime.utcnow(),
                access_count=1,
            ),
            SearchResult(
                memory_id="m2",
                session_id="s2",
                session_type="shopping",
                user_intent="buy laptop",
                action_sequence=["search", "add_to_cart"],
                key_entities=[],
                similarity_score=0.8,
                created_at=datetime.utcnow(),
                accessed_at=datetime.utcnow(),
                access_count=1,
            ),
        ]

        suggestions = engine._suggest_actions(similar_sessions, {})

        assert "search" in suggestions
        assert "add_to_cart" in suggestions
