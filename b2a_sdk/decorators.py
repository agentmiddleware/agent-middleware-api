"""
B2A SDK Decorators
===================

Developer Experience decorators for agent tools.

- @monitored: Wires function telemetry to the Autonomous PM
- @billable: Gates function execution behind the billing engine

Both decorators use asyncio.create_task for non-blocking execution.
"""

import asyncio
import functools
import time
import traceback
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from .client import B2AClient

P = ParamSpec("P")
T = TypeVar("T")


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

    Usage:
        b2a = B2AClient(api_key="agt-xyz123")

        @billable(b2a, wallet_id="agt-123", service_category="content_factory", units=5.0)
        async def generate_video(url: str):
            # This only runs if wallet has 5+ credits
            pass

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
