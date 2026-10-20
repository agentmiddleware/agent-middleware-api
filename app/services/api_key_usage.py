"""
API Key Usage Event Tracking

Records per-call usage events for API keys after successful authentication.
Events are written asynchronously without blocking the request path.
A failed write never fails the request.
"""

import logging
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.time import to_naive_utc, utc_now
from ..db.database import get_session_factory
from ..db.models import APIKeyUsageEventModel

logger = logging.getLogger(__name__)


async def record_api_key_usage_event(
    key_id: str,
    tenant: Optional[str],
    method: str,
    route_template: str,
    status_code: int,
    latency_ms: int,
) -> None:
    """
    Record one API key usage event asynchronously.

    Args:
        key_id: The API key ID that authenticated
        tenant: The tenant label (None = normal, "demo" = demo tenant)
        method: HTTP method (GET, POST, etc.)
        route_template: The route template (not the raw path with IDs)
        status_code: HTTP response status code
        latency_ms: Request latency in milliseconds

    This function never raises. A failed write is logged and the request
    continues unchanged. No request bodies, IPs, headers, or PII are stored.
    """
    try:
        event_id = f"ue_{uuid4().hex[:16]}"
        now = to_naive_utc(utc_now())

        event = APIKeyUsageEventModel(
            id=event_id,
            key_id=key_id,
            tenant=tenant,
            method=method[:10],  # Truncate to column size
            route_template=route_template[:255],  # Truncate to column size
            status_code=status_code,
            latency_ms=latency_ms,
            created_at=now,
        )

        session_factory = get_session_factory()
        async with session_factory()() as session:
            session.add(event)
            await session.commit()

        logger.debug(
            f"Recorded usage event {event_id} for key {key_id}: "
            f"{method} {route_template} -> {status_code} ({latency_ms}ms)"
        )
    except Exception as e:
        # A failed write never fails the request. Log and continue.
        logger.error(
            f"Failed to record API key usage event for key {key_id}: {e}",
            exc_info=True,
        )
