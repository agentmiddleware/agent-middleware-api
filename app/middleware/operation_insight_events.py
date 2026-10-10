"""Default-off, payload-free gateway ingress and terminal observations."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.core.config import get_settings
from app.services.operation_insights.events import (
    InsightEvent,
    RequestEventContext,
    activate_request,
    deactivate_request,
    enrich_ingress_bounded,
    normalize_client_version,
    observe_event_bounded,
    original_anchor,
    safe_server_release,
)
from app.services.operation_insights.contracts import RequestDisposition


_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_REST_INVOKE = re.compile(r"\A/mcp/tools/[^/]+/invoke\Z")


def _safe_id(value: str | None) -> str | None:
    return value if value is not None and _SAFE_ID.fullmatch(value) else None


def _strict_ascii(value: bytes | None) -> str | None:
    if value is None:
        return None
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return None


def _client_version_header(scope: dict[str, Any]) -> str | None:
    values = [
        value
        for key, value in scope.get("headers", ())
        if key.lower() == b"x-client-version"
    ]
    return _strict_ascii(values[0]) if len(values) == 1 else None


def _disposition(method: str, path: str) -> RequestDisposition | None:
    if method == "POST" and _REST_INVOKE.fullmatch(path):
        return "execution_intent"
    if method == "POST" and path in {"/mcp", "/mcp/messages"}:
        return "unknown"
    if method in {"GET", "HEAD", "DELETE"} and path in {"/mcp", "/mcp/messages"}:
        return "non_execution_read"
    return None


class OperationInsightEventsMiddleware:
    """Observe only known MCP routes without consuming or decoding request bodies."""

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        enabled: bool | None = None,
    ) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        settings = get_settings()
        if scope["type"] != "http" or not (
            settings.OPERATION_INSIGHTS_EVENTS_ENABLED
            if self.enabled is None
            else self.enabled
        ):
            await self.app(scope, receive, send)
            return
        disposition = _disposition(scope.get("method", ""), scope.get("path", ""))
        if disposition is None:
            await self.app(scope, receive, send)
            return

        nonce = uuid.uuid4().hex
        request_id = f"req-{nonce}"
        metadata: dict[str, Any] = {
            "request_id": request_id,
            "request_disposition": disposition,
            "environment": _safe_id(settings.ENVIRONMENT),
            "server_release": safe_server_release(),
            "deployment": _safe_id(os.environ.get("RAILWAY_DEPLOYMENT_ID")),
            "client_version": normalize_client_version(
                _client_version_header(scope),
                frozenset(
                    part.strip()
                    for part in settings.OPERATION_INSIGHTS_ALLOWED_CLIENT_VERSIONS.split(
                        ","
                    )
                    if part.strip()
                ),
            ),
        }
        await observe_event_bounded(
            InsightEvent(
                event_id=f"evt-{nonce}-ingress",
                kind="ingress",
                occurred_at=datetime.now(timezone.utc),
                **metadata,
            )
        )
        context = RequestEventContext(
            request_id=request_id,
            ingress_event_id=f"evt-{nonce}-ingress",
            request_disposition=disposition,
            client_version=metadata["client_version"],
            environment=metadata["environment"],
            server_release=metadata["server_release"],
            deployment=metadata["deployment"],
        )
        token = activate_request(context)

        status_code: int | None = None
        response_complete = False

        async def observe_send(message: dict[str, Any]) -> None:
            nonlocal status_code, response_complete
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                response_complete = True

        try:
            await self.app(scope, receive, observe_send)
        finally:
            try:
                await enrich_ingress_bounded(context)
                if response_complete:
                    await observe_event_bounded(
                        InsightEvent(
                            event_id=f"evt-{nonce}-terminal",
                            kind="terminal",
                            occurred_at=datetime.now(timezone.utc),
                            http_status_code=status_code,
                            reason_code=context.reason_code,
                            gateway_outcome=(
                                context.gateway_outcome
                                if context.gateway_outcome is not None
                                else "failed"
                                if status_code is not None and status_code >= 500
                                else "denied"
                                if status_code is not None and status_code >= 400
                                else None
                            ),
                            effect_state="unknown",
                            **{
                                **metadata,
                                "request_disposition": context.request_disposition,
                                "wallet_id": context.wallet_id,
                                "tool": context.tool,
                                "logical_operation_id": context.logical_operation_id,
                                "original_operation_anchor_id": original_anchor(
                                    context
                                ),
                            },
                        )
                    )
            finally:
                deactivate_request(token)
