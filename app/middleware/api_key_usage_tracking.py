"""
API Key Usage Tracking Middleware

Records API key usage events after each authenticated request completes.
Captures method, route template, status code, and latency without blocking
the response path. A failed write never fails the request.
"""

import asyncio
import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.auth import CREDENTIAL_ACCEPTANCE, CURRENT_AUTH_CONTEXT

logger = logging.getLogger(__name__)


class APIKeyUsageTrackingMiddleware(BaseHTTPMiddleware):
    """
    Records API key usage events after authenticated requests complete.

    This middleware runs after authentication resolves an API key and captures:
    - key_id: The authenticated API key
    - tenant: The tenant label from the key
    - method: HTTP method
    - route_template: The matched route template (not the raw path)
    - status_code: Response status code
    - latency_ms: Request duration in milliseconds

    A failed write is logged and never blocks the response.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Store start time in request state so we can track it after auth
        request.state.usage_tracking_start = start_time

        # Process the request (this will call auth and handlers)
        response = await call_next(request)

        # Only record for authenticated requests
        acceptance = CREDENTIAL_ACCEPTANCE.get()
        if acceptance is None or not acceptance.accepted:
            return response

        # Extract AuthContext from ContextVar (set by get_auth_context)
        auth_context = CURRENT_AUTH_CONTEXT.get()
        if auth_context is None:
            # Not authenticated or auth context not available
            return response

        if auth_context.key_id is None:
            # Bootstrap admin or static dev key - no usage tracking
            return response

        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Determine route template
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            route_template = route.path
        else:
            # Fallback to raw path if route template unavailable
            route_template = request.url.path

        # Record usage event asynchronously (fire and forget)
        asyncio.create_task(
            self._record_usage_event(
                key_id=auth_context.key_id,
                tenant=auth_context.tenant,
                method=request.method,
                route_template=route_template,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )
        )

        return response

    async def _record_usage_event(
        self,
        key_id: str,
        tenant: str | None,
        method: str,
        route_template: str,
        status_code: int,
        latency_ms: int,
    ) -> None:
        """
        Record the usage event. This runs asynchronously and never blocks.
        """
        try:
            from ..services.api_key_usage import record_api_key_usage_event

            await record_api_key_usage_event(
                key_id=key_id,
                tenant=tenant,
                method=method,
                route_template=route_template,
                status_code=status_code,
                latency_ms=latency_ms,
            )
        except Exception as e:
            # Catch-all: even if the import or call fails, don't block
            logger.error(
                f"Failed to record API key usage event for {key_id}: {e}",
                exc_info=True,
            )
