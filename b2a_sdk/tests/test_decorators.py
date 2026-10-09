"""Focused tests for ``b2a_sdk.decorators``.

Covers the main public behavior of each decorator (``monitored``,
``billable``, ``combined``, ``mcp_tool``) plus the registration-callback
hook, including edge and error cases. No network access: the client is a
``MagicMock`` and telemetry is fire-and-forget, so no real services run.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from b2a_sdk import B2AClient, InsufficientFundsError, billable, combined, monitored
from b2a_sdk.decorators import (
    _registration_callbacks,
    mcp_tool,
    register_mcp_tool_callback,
)


@pytest.fixture
def mock_client():
    client = MagicMock(spec=B2AClient)
    client.telemetry = AsyncMock()
    client.charge = AsyncMock()
    return client


@pytest.fixture
def clean_registration_callbacks():
    """Snapshot the global callback list so tests do not leak into each other."""
    saved = list(_registration_callbacks)
    _registration_callbacks.clear()
    try:
        yield
    finally:
        _registration_callbacks.clear()
        _registration_callbacks.extend(saved)


async def _drain_telemetry():
    """Let fire-and-forget telemetry tasks run to avoid stray coroutines."""
    await asyncio.sleep(0)


class TestMonitored:
    @pytest.mark.asyncio
    async def test_async_success_returns_value_and_reports_success(self, mock_client):
        @monitored(mock_client, service_name="svc")
        async def fetch(url):
            return f"ok:{url}"

        assert await fetch("x") == "ok:x"
        await _drain_telemetry()
        mock_client.telemetry.assert_called_once()
        call_kwargs = mock_client.telemetry.call_args.kwargs
        assert call_kwargs["event_type"] == "api_call"
        assert call_kwargs["source"] == "svc"
        assert call_kwargs["severity"] == "info"
        assert call_kwargs["status"] == "success"
        assert fetch.__name__ == "fetch"

    @pytest.mark.asyncio
    async def test_async_error_reraises_and_hides_secret_by_default(self, mock_client):
        @monitored(mock_client, service_name="svc")
        async def explode():
            raise ValueError("token-hunter2")

        with pytest.raises(ValueError, match="token-hunter2"):
            await explode()
        await _drain_telemetry()
        call_kwargs = mock_client.telemetry.call_args.kwargs
        assert call_kwargs["event_type"] == "error"
        assert call_kwargs["error_type"] == "ValueError"
        assert "token-hunter2" not in repr(call_kwargs)
        assert "stack_trace" not in call_kwargs

    @pytest.mark.asyncio
    async def test_capture_args_records_arguments(self, mock_client):
        @monitored(mock_client, service_name="svc", capture_args=True)
        async def run(job_id, *, verbose=False):
            return job_id

        assert await run("42", verbose=True) == "42"
        await _drain_telemetry()
        call_kwargs = mock_client.telemetry.call_args.kwargs
        assert "42" in call_kwargs["args"]
        assert call_kwargs["kwargs"] == {"verbose": "True"}

    def test_sync_without_running_loop_still_returns_value(self, mock_client):
        @monitored(mock_client, service_name="svc")
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_sync_without_running_loop_reraises_original_error(self, mock_client):
        @monitored(mock_client, service_name="svc")
        def explode():
            raise ValueError("original failure")

        with pytest.raises(ValueError, match="original failure"):
            explode()


class TestBillable:
    @pytest.mark.asyncio
    async def test_charges_before_running_function(self, mock_client):
        order = []

        @billable(mock_client, wallet_id="w-1", service_category="cat", units=5.0)
        async def work():
            order.append("ran")
            return "done"

        assert await work() == "done"
        assert order == ["ran"]
        mock_client.charge.assert_awaited_once()
        call_kwargs = mock_client.charge.call_args.kwargs
        assert call_kwargs["wallet_id"] == "w-1"
        assert call_kwargs["service_category"] == "cat"
        assert call_kwargs["units"] == 5.0

    @pytest.mark.asyncio
    async def test_insufficient_funds_skips_function_body(self, mock_client):
        mock_client.charge.side_effect = InsufficientFundsError(
            wallet_id="w-1",
            shortfall=10.0,
            top_up_url="http://test/top-up",
        )
        ran = False

        @billable(mock_client, wallet_id="w-1", service_category="cat")
        async def work():
            nonlocal ran
            ran = True

        with pytest.raises(InsufficientFundsError):
            await work()
        assert ran is False

    def test_sync_function_rejected_when_called(self, mock_client):
        ran = False

        @billable(mock_client, wallet_id="w-1", service_category="cat")
        def work():
            nonlocal ran
            ran = True

        with pytest.raises(RuntimeError, match="requires an async function"):
            work()
        assert ran is False
        mock_client.charge.assert_not_called()


class TestCombined:
    @pytest.mark.asyncio
    async def test_charges_and_emits_telemetry(self, mock_client):
        @combined(
            mock_client,
            wallet_id="w-1",
            service_category="cat",
            service_name="svc",
        )
        async def work():
            return "done"

        assert await work() == "done"
        await _drain_telemetry()
        mock_client.charge.assert_awaited_once()
        mock_client.telemetry.assert_called_once()
        assert mock_client.telemetry.call_args.kwargs["source"] == "svc"


class TestMcpTool:
    @pytest.mark.asyncio
    async def test_registers_metadata_and_preserves_behavior(self, clean_registration_callbacks):
        seen = []
        register_mcp_tool_callback(
            lambda service_id, func, input_schema, output_schema: seen.append(service_id)
        )

        @mcp_tool(
            service_id="video-generator",
            name="Video Generator",
            description="Makes videos",
            category="content",
            credits_per_unit=10.0,
        )
        async def generate_video(url: str, style: str = "cinematic"):
            """Generate a video."""
            return {"video_url": url}

        assert await generate_video("u") == {"video_url": "u"}
        assert seen == ["video-generator"]
        metadata = generate_video._b2a_mcp_metadata
        assert metadata["service_id"] == "video-generator"
        assert metadata["name"] == "Video Generator"
        assert metadata["description"] == "Makes videos"
        assert metadata["category"] == "content"
        assert metadata["credits_per_unit"] == 10.0
        assert generate_video.__name__ == "generate_video"
        required = metadata["input_schema"]["required"]
        assert "url" in required
        assert "style" not in required

    @pytest.mark.asyncio
    async def test_defaults_name_and_description(self, clean_registration_callbacks):
        @mcp_tool(service_id="svc")
        async def my_tool(query):
            """Docstring description."""
            return query

        assert await my_tool("q") == "q"
        assert my_tool._b2a_mcp_metadata["name"] == "my_tool"
        assert my_tool._b2a_mcp_metadata["description"] == "Docstring description."

    @pytest.mark.asyncio
    async def test_no_params_yields_no_input_schema(self, clean_registration_callbacks):
        @mcp_tool(service_id="ping")
        async def ping():
            return "pong"

        assert await ping() == "pong"
        assert ping._b2a_mcp_metadata["input_schema"] is None

    @pytest.mark.asyncio
    async def test_failing_callback_does_not_break_registration(self, clean_registration_callbacks):
        def bad_callback(service_id, func, input_schema, output_schema):
            raise RuntimeError("callback blew up")

        register_mcp_tool_callback(bad_callback)

        @mcp_tool(service_id="svc")
        async def my_tool():
            return "ok"

        assert await my_tool() == "ok"
