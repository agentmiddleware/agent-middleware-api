"""
Tests for v1.1 Production Hardening Features
============================================

Tests for:
1. Structured logging
2. Health/ready endpoint
3. Retry with backoff
4. Circuit breakers
5. MCP pagination
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


class TestResilienceUtilities:
    """Tests for resilience utilities."""

    def test_retry_with_backoff_success(self):
        """Test retry decorator succeeds on first attempt."""
        from app.core.resilience import retry_with_backoff

        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.1)
        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = asyncio.run(success_func())
        assert result == "success"
        assert call_count == 1

    def test_retry_with_backoff_retry(self):
        """Test retry decorator retries on failure."""
        from app.core.resilience import retry_with_backoff

        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Transient error")
            return "success"

        result = asyncio.run(flaky_func())
        assert result == "success"
        assert call_count == 3

    def test_circuit_breaker_closed_state(self):
        """Test circuit breaker starts closed."""
        from app.core.resilience import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.is_allowed() is True

    def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit breaker opens after failures."""
        from app.core.resilience import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.is_allowed() is False

    def test_circuit_breaker_record_success(self):
        """Test circuit breaker records success."""
        from app.core.resilience import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb._failure_count == 1


class TestMCPPagination:
    """Tests for MCP pagination."""

    def test_pagination_response_fields(self):
        """Verify pagination returns expected fields."""
        from app.routers.mcp import list_tools
        import inspect

        sig = inspect.signature(list_tools)
        params = list(sig.parameters.keys())

        assert "limit" in params
        assert "offset" in params
        assert "category" in params


class TestHealthEndpoints:
    """Tests for health endpoints."""

    def test_health_endpoint_exists(self):
        """Verify /health endpoint exists."""
        from app.main import app

        routes = [r.path for r in app.routes]
        assert "/health" in routes

    def test_health_ready_endpoint_exists(self):
        """Verify /health/ready endpoint exists."""
        from app.main import app

        routes = [r.path for r in app.routes]
        assert "/health/ready" in routes


class TestStructuredLogging:
    """Tests for structured logging."""

    def test_structlog_available(self):
        """Test that structlog can be imported."""
        try:
            import structlog

            assert hasattr(structlog, "configure")
            assert hasattr(structlog, "get_logger")
        except ImportError:
            pytest.skip("structlog not installed")

    def test_resilience_logger_integration(self):
        """Test that resilience logger works without structlog."""
        from app.core.resilience import retry_with_backoff

        call_count = 0

        @retry_with_backoff(max_attempts=2, base_delay=0.01)
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            asyncio.run(failing_func())

        assert call_count == 2  # Initial + 1 retry
