"""
Tests for the Behavioral Sandbox Engine — Phase 6
"""

import pytest
from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.sandbox_behavioral import (
    SandboxEnvironmentCreate,
    SandboxEnvironmentType,
    ToolExecutionRequest,
)
from app.services.behavioral_sandbox import BehavioralSandboxEngine


@pytest.fixture
def engine():
    """Create a fresh engine for testing."""
    engine = BehavioralSandboxEngine(redis_url="redis://localhost:6379")
    return engine


@pytest.fixture
def sample_env_request():
    """Sample environment creation request."""
    return SandboxEnvironmentCreate(
        name="test-environment",
        environment_type=SandboxEnvironmentType.PYTHON_SUBPROCESS,
        timeout_seconds=10,
        memory_limit_mb=128,
        network_access=False,
    )


class TestBehavioralSandboxSchemas:
    """Test schema validation."""

    def test_sandbox_environment_create_defaults(self):
        """Test default values for environment creation."""
        req = SandboxEnvironmentCreate(name="test")
        assert req.environment_type == SandboxEnvironmentType.PYTHON_SUBPROCESS
        assert req.timeout_seconds == 30
        assert req.memory_limit_mb == 256
        assert req.network_access is False
        assert req.env_vars == {}

    def test_sandbox_environment_types(self):
        """Test all environment types are valid."""
        for env_type in SandboxEnvironmentType:
            req = SandboxEnvironmentCreate(
                name="test",
                environment_type=env_type,
            )
            assert req.environment_type == env_type

    def test_tool_execution_request(self):
        """Test tool execution request schema."""
        req = ToolExecutionRequest(
            env_id="sandbox-test-123",
            tool_name="test_tool",
            tool_input={"param": "value"},
            dry_run=True,
        )
        assert req.env_id == "sandbox-test-123"
        assert req.tool_name == "test_tool"
        assert req.dry_run is True


class TestBehavioralSandboxEngine:
    """Test the behavioral sandbox engine."""

    @pytest.mark.anyio
    async def test_create_environment(self, engine, sample_env_request):
        """Test environment creation."""
        env = await engine.create_environment(sample_env_request)

        assert env.env_id.startswith("sandbox-")
        assert env.name == "test-environment"
        assert env.environment_type == SandboxEnvironmentType.PYTHON_SUBPROCESS
        assert env.status == "created"
        assert env.timeout_seconds == 10
        assert env.memory_limit_mb == 128

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_create_mcp_sandbox_environment(self, engine):
        """Test MCP sandbox environment creation."""
        req = SandboxEnvironmentCreate(
            name="mcp-test",
            environment_type=SandboxEnvironmentType.MCP_SANDBOX,
        )
        env = await engine.create_environment(req)

        assert env.environment_type == SandboxEnvironmentType.MCP_SANDBOX
        assert env.status == "created"

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_execute_python_subprocess(self, engine, sample_env_request):
        """Test Python subprocess execution."""
        env = await engine.create_environment(sample_env_request)

        request = ToolExecutionRequest(
            env_id=env.env_id,
            tool_name="hello_world",
            tool_input={"code": "print('hello from sandbox')"},
            dry_run=True,
        )

        result = await engine.execute_tool(request)

        assert result.env_id == env.env_id
        assert result.tool_name == "hello_world"
        assert result.status.value in ["success", "failed"]
        assert result.started_at is not None

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_execute_mcp_sandbox(self, engine):
        """Test MCP sandbox tool execution."""
        req = SandboxEnvironmentCreate(
            name="mcp-exec-test",
            environment_type=SandboxEnvironmentType.MCP_SANDBOX,
        )
        env = await engine.create_environment(req)

        request = ToolExecutionRequest(
            env_id=env.env_id,
            tool_name="get_weather",
            tool_input={"location": "San Francisco"},
            dry_run=True,
        )

        result = await engine.execute_tool(request)

        assert result.status.value == "success"
        assert result.output is not None
        assert result.cost_estimate is not None

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_execute_with_real_code(self, engine, sample_env_request):
        """Test execution with actual Python code."""
        env = await engine.create_environment(sample_env_request)

        request = ToolExecutionRequest(
            env_id=env.env_id,
            tool_name="calculator",
            tool_input={
                "code": "result = 2 + 2\nprint(f'Result: {result}')",
                "context": {},
            },
            dry_run=False,
        )

        result = await engine.execute_tool(request)

        assert result.status.value in ["success", "failed"]

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_environment_not_found(self, engine):
        """Test execution with non-existent environment."""
        request = ToolExecutionRequest(
            env_id="nonexistent-env",
            tool_name="test",
            tool_input={},
        )

        with pytest.raises(ValueError, match="not found"):
            await engine.execute_tool(request)

    @pytest.mark.anyio
    async def test_get_environment_state(self, engine, sample_env_request):
        """Test getting environment state."""
        env = await engine.create_environment(sample_env_request)

        state = await engine.get_environment_state(env.env_id)

        assert state["env_id"] == env.env_id
        assert state["status"] == "created"
        assert "executions" in state
        assert "metrics" in state

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_destroy_environment(self, engine, sample_env_request):
        """Test environment destruction."""
        env = await engine.create_environment(sample_env_request)
        env_id = env.env_id

        result = await engine.destroy_environment(env_id)
        assert result is True

        with pytest.raises(ValueError, match="not found"):
            await engine.get_environment_state(env_id)

    @pytest.mark.anyio
    async def test_multiple_executions(self, engine, sample_env_request):
        """Test multiple executions in same environment."""
        env = await engine.create_environment(sample_env_request)

        for i in range(3):
            request = ToolExecutionRequest(
                env_id=env.env_id,
                tool_name=f"test_{i}",
                tool_input={"code": f"print('test {i}')"},
                dry_run=True,
            )
            result = await engine.execute_tool(request)
            assert result.status.value in ["success", "failed"]

        state = await engine.get_environment_state(env.env_id)
        assert state["metrics"]["total_executions"] == 3

        await engine.destroy_environment(env.env_id)

    @pytest.mark.anyio
    async def test_metrics_calculation(self, engine, sample_env_request):
        """Test metrics are calculated correctly."""
        env = await engine.create_environment(sample_env_request)

        request = ToolExecutionRequest(
            env_id=env.env_id,
            tool_name="metrics_test",
            tool_input={"code": "print('test')"},
            dry_run=True,
        )

        await engine.execute_tool(request)
        await engine.execute_tool(request)

        state = await engine.get_environment_state(env.env_id)
        metrics = state["metrics"]

        assert metrics["total_executions"] == 2
        assert metrics["avg_execution_time_ms"] >= 0

        await engine.destroy_environment(env.env_id)


class TestBehavioralSandboxRouter:
    """Test the behavioral sandbox router endpoints."""

    @pytest.fixture
    def api_headers(self):
        return {"X-API-Key": "test-key"}

    @pytest.mark.anyio
    async def test_create_environment_endpoint_requires_api_key(self):
        """Behavioral sandbox endpoints require authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/sandbox/behavioral/environments",
                json={"name": "unauthenticated"},
            )

            assert response.status_code == 401

    @pytest.mark.anyio
    async def test_create_environment_endpoint(self, api_headers):
        """Test POST /v1/sandbox/behavioral/environments."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/sandbox/behavioral/environments",
                json={
                    "name": "router-test",
                    "environment_type": "python_subprocess",
                    "timeout_seconds": 10,
                },
                headers=api_headers,
            )

            assert response.status_code == 201
            data = response.json()
            assert "env_id" in data
            assert data["name"] == "router-test"

    @pytest.mark.anyio
    async def test_execute_tool_endpoint(self, api_headers):
        """Test POST /v1/sandbox/behavioral/execute."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_response = await client.post(
                "/v1/sandbox/behavioral/environments",
                json={"name": "execute-test"},
                headers=api_headers,
            )
            env_id = create_response.json()["env_id"]

            response = await client.post(
                "/v1/sandbox/behavioral/execute",
                json={
                    "env_id": env_id,
                    "tool_name": "test_tool",
                    "tool_input": {"code": "print('hello')"},
                    "dry_run": True,
                },
                headers=api_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "execution_id" in data
            assert data["env_id"] == env_id

    @pytest.mark.anyio
    async def test_get_environment_endpoint(self, api_headers):
        """Test GET /v1/sandbox/behavioral/environments/{env_id}."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_response = await client.post(
                "/v1/sandbox/behavioral/environments",
                json={"name": "get-test"},
                headers=api_headers,
            )
            env_id = create_response.json()["env_id"]

            response = await client.get(
                f"/v1/sandbox/behavioral/environments/{env_id}",
                headers=api_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["env_id"] == env_id

    @pytest.mark.anyio
    async def test_delete_environment_endpoint(self, api_headers):
        """Test DELETE /v1/sandbox/behavioral/environments/{env_id}."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_response = await client.post(
                "/v1/sandbox/behavioral/environments",
                json={"name": "delete-test"},
                headers=api_headers,
            )
            env_id = create_response.json()["env_id"]

            response = await client.delete(
                f"/v1/sandbox/behavioral/environments/{env_id}",
                headers=api_headers,
            )

            assert response.status_code == 204

    @pytest.mark.anyio
    async def test_execute_nonexistent_environment(self, api_headers):
        """Test execution on non-existent environment returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/sandbox/behavioral/execute",
                json={
                    "env_id": "nonexistent",
                    "tool_name": "test",
                    "tool_input": {},
                },
                headers=api_headers,
            )

            assert response.status_code == 404
