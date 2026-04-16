"""
B2A SDK Decorators
==================

Developer Experience decorators for agent tools.

- @monitored: Wires function telemetry to the Autonomous PM
- @billable: Gates function execution behind the billing engine
- @mcp_tool: Registers a function as an MCP tool with auto-discovery

Both decorators use asyncio.create_task for non-blocking execution.
"""

import asyncio
import contextvars
import functools
import inspect
import time
import traceback
from collections.abc import Callable
from typing import ParamSpec, TypeVar, get_type_hints

from .client import B2AClient, DryRunSimulation

P = ParamSpec("P")
T = TypeVar("T")

_registration_callbacks: list[Callable] = []

_dry_run_context: contextvars.ContextVar[DryRunSimulation | None] = contextvars.ContextVar(
    "dry_run_context", default=None
)


def register_mcp_tool_callback(callback: Callable) -> None:
    """
    Register a callback to be called when @mcp_tool is used.

    This allows the SDK to auto-register tools with the backend.
    """
    _registration_callbacks.append(callback)


def _notify_registration(service_id: str, func: Callable, input_schema: dict | None, output_schema: dict | None) -> None:
    """Notify all registered callbacks of a new MCP tool."""
    for callback in _registration_callbacks:
        try:
            callback(service_id, func, input_schema, output_schema)
        except Exception:
            pass


def _extract_schema_from_func(func: Callable) -> tuple[dict | None, dict | None]:
    """Extract input/output schemas from a function signature."""
    try:
        sig = inspect.signature(func)
        hints = get_type_hints(func) if func else {}

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            hint = hints.get(param_name)
            if hint is None:
                properties[param_name] = {"type": "string"}
            elif hasattr(hint, "model_json_schema"):
                properties[param_name] = hint.model_json_schema()
            elif hasattr(hint, "schema"):
                properties[param_name] = hint.schema()
            else:
                type_str = getattr(hint, "__name__", str(hint))
                properties[param_name] = {"type": type_str}

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        input_schema = {
            "type": "object",
            "properties": properties,
            "required": required,
        } if properties else None

        return_type = hints.get("return")
        output_schema = None
        if return_type and return_type is not type(None):
            if hasattr(return_type, "model_json_schema"):
                output_schema = return_type.model_json_schema()
            elif hasattr(return_type, "schema"):
                output_schema = return_type.schema()

        return input_schema, output_schema

    except Exception:
        return None, None


def monitored(
    client: B2AClient,
    service_name: str,
    capture_args: bool = False,
):
    """
    Instantly wires a function to the Autonomous Product Manager.

    Tracks execution latency, success/failure status, and captures
    stack traces on error. Telemetry is fired in the background
    using asyncio.create_task to add zero latency to execution.

    Usage:
        b2a = B2AClient(api_key="agt-xyz123")

        @monitored(b2a, service_name="web_scraper")
        async def scrape_website(url: str):
            # Your agent logic here...
            pass

    Args:
        client: B2AClient instance for telemetry submission
        service_name: Name of the service/module (appears in telemetry)
        capture_args: If True, includes function args in metadata

    Returns:
        Decorator function
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start_time = time.time()
            metadata = {}

            if capture_args:
                metadata["args"] = str(args)[:200]
                metadata["kwargs"] = {k: str(v)[:200] for k, v in kwargs.items()}

            try:
                result = await func(*args, **kwargs)

                latency_ms = int((time.time() - start_time) * 1000)
                metadata["latency_ms"] = latency_ms
                metadata["status"] = "success"

                asyncio.create_task(
                    client.telemetry(
                        event_type="api_call",
                        source=service_name,
                        message=f"Successfully executed {func.__name__}",
                        severity="info",
                        function=func.__name__,
                        **metadata,
                    )
                )

                return result

            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)

                asyncio.create_task(
                    client.telemetry(
                        event_type="error",
                        source=service_name,
                        message=f"Error in {func.__name__}: {str(e)}",
                        severity="high",
                        function=func.__name__,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        latency_ms=latency_ms,
                        status="failed",
                    )
                )

                raise

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start_time = time.time()
            metadata = {}

            if capture_args:
                metadata["args"] = str(args)[:200]
                metadata["kwargs"] = {k: str(v)[:200] for k, v in kwargs.items()}

            try:
                result = func(*args, **kwargs)

                latency_ms = int((time.time() - start_time) * 1000)
                metadata["latency_ms"] = latency_ms
                metadata["status"] = "success"

                asyncio.create_task(
                    client.telemetry(
                        event_type="api_call",
                        source=service_name,
                        message=f"Successfully executed {func.__name__}",
                        severity="info",
                        function=func.__name__,
                        **metadata,
                    )
                )

                return result

            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)

                asyncio.create_task(
                    client.telemetry(
                        event_type="error",
                        source=service_name,
                        message=f"Error in {func.__name__}: {str(e)}",
                        severity="high",
                        function=func.__name__,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        latency_ms=latency_ms,
                        status="failed",
                    )
                )

                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def billable(
    client: B2AClient,
    wallet_id: str,
    service_category: str,
    units: float = 1.0,
    request_path: str | None = None,
):
    """
    Gates function execution behind the Agent Financial Gateway.

    Before executing the function, the SDK attempts to charge the wallet.
    If the wallet has insufficient funds, InsufficientFundsError is raised
    and the function never executes.

    When called within a `simulate_session()` context, the charge is
    simulated without affecting real balance or triggering velocity monitoring.

    Usage:
        b2a = B2AClient(api_key="agt-xyz123")

        @billable(b2a, wallet_id="agt-123", service_category="content_factory", units=5.0)
        async def generate_video(url: str):
            # This only runs if wallet has 5+ credits
            pass

        # Or with simulation:
        async with b2a.simulate_session(wallet_id="agt-123") as sim:
            await generate_video(url)  # Simulated charge
            print(f"Simulated cost: {sim.total_cost}")

    Args:
        client: B2AClient instance for billing
        wallet_id: Wallet to charge
        service_category: Service category for pricing
        units: Number of units to charge (default: 1.0)
        request_path: Optional API path for tracking

    Returns:
        Decorator function

    Raises:
        InsufficientFundsError: If wallet balance is insufficient
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            sim = _dry_run_context.get()

            if sim is not None and sim._active:
                result = await client.simulate_charge(
                    wallet_id=wallet_id,
                    service_category=service_category,
                    units=units,
                    session_id=sim.session_id,
                    description=request_path or f"{func.__module__}.{func.__name__}",
                )
                sim.add_charge_result(result)
                return await func(*args, **kwargs)

            await client.charge(
                wallet_id=wallet_id,
                service_category=service_category,
                units=units,
                request_path=request_path or f"{func.__module__}.{func.__name__}",
            )
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            raise RuntimeError(
                "@billable requires an async function. "
                f"Got sync function: {func.__name__}"
            )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def combined(
    client: B2AClient,
    wallet_id: str,
    service_category: str,
    service_name: str,
    units: float = 1.0,
    request_path: str | None = None,
):
    """
    Combines @monitored and @billable into a single decorator.

    This is the recommended decorator for billable agent tools
    that you want telemetry on.

    Usage:
        @combined(b2a, wallet_id="agt-123", service_category="content_factory",
                  service_name="video_generator", units=5.0)
        async def generate_video(url: str):
            pass

    Args:
        client: B2AClient instance
        wallet_id: Wallet to charge
        service_category: Service category for pricing
        service_name: Name for telemetry
        units: Units to charge
        request_path: Optional API path

    Returns:
        Decorator function
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        monitored_decorator = monitored(client, service_name)
        billable_decorator = billable(
            client, wallet_id, service_category, units, request_path
        )

        decorated = billable_decorator(monitored_decorator(func))

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await decorated(*args, **kwargs)

        return wrapper

    return decorator


def mcp_tool(
    service_id: str,
    name: str | None = None,
    description: str | None = None,
    category: str = "custom",
    credits_per_unit: float = 1.0,
    unit_name: str = "call",
):
    """
    Decorator to register a function as an MCP tool.

    When applied, the function is automatically registered with the
    B2A service registry and exposed via MCP.

    Usage:
        @mcp_tool(
            service_id="video-generator",
            name="Video Generator",
            description="Generate a video from a URL",
            category="content_factory",
            credits_per_unit=10.0,
        )
        async def generate_video(url: str, style: str = "cinematic") -> dict:
            # Your implementation here
            return {"video_url": f"https://example.com/{url}.mp4"}

    Args:
        service_id: Unique identifier for the service (used in MCP calls)
        name: Human-readable name (defaults to function name)
        description: Service description (defaults to docstring or "No description")
        category: Service category for pricing
        credits_per_unit: Credits to charge per call
        unit_name: Unit name for pricing display

    Returns:
        Decorator function
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        actual_name = name or func.__name__
        actual_description = description or func.__doc__ or "No description"

        input_schema, output_schema = _extract_schema_from_func(func)

        _notify_registration(
            service_id=service_id,
            func=func,
            input_schema=input_schema,
            output_schema=output_schema,
        )

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await func(*args, **kwargs)

        wrapper._b2a_mcp_metadata = {
            "service_id": service_id,
            "name": actual_name,
            "description": actual_description,
            "category": category,
            "credits_per_unit": credits_per_unit,
            "unit_name": unit_name,
            "input_schema": input_schema,
            "output_schema": output_schema,
        }

        return wrapper

    return decorator
