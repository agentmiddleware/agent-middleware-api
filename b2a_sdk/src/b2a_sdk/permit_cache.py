"""A small bounded cache for framework-wrapper permit ids.

Framework wrappers (autogen, crewai, langchain) keep one permit per caller
supplied permit idempotency key, so a replay reuses the recorded permit
instead of sending a fresh ``expires_at`` under the same key (which the
server refuses as an idempotency conflict). That cache must not grow without
bound and must not keep serving a permit the wrapper already knows is dead,
so each entry carries the permit's own expiry and the cache evicts the least
recently used entry past a small cap.

The cache also keeps the original permit request body alongside the permit
id. A revoked or expired permit poisons its key: the next attempt under the
same key re-sends the identical body, so the server replays the same denial
instead of seeing a fresh timestamp and reporting a conflict. Dropping only
the permit id (``drop_permit``) preserves that stable denial.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .errors import PermitDeniedError
from .models import Permit, PermitRequest

#: Default cap on cached permits per wrapper instance. Wrapper instances are
#: per agent, so a few dozen live permits is already generous.
DEFAULT_MAXSIZE = 128

#: Server denial reasons that mean the cached permit is dead and must be
#: dropped. Anything else (wallet mismatch, scope problems, unknown permit)
#: is a configuration problem, and the stable replayed denial is more useful
#: than a fresh request under the same key.
PERMIT_LIFECYCLE_DENIALS = frozenset({"permit_expired", "permit_revoked"})


def is_permit_lifecycle_denial(exc: BaseException) -> bool:
    """Whether ``exc`` reports a revoked or expired permit.

    The trust plane surfaces both as a ``PermitDeniedError`` whose reason is
    the server's own vocabulary (``permit_expired``, ``permit_revoked``).
    """
    reason = getattr(exc, "reason", None)
    if reason is None and isinstance(exc, PermitDeniedError):
        reason = exc.detail
    return isinstance(reason, str) and reason in PERMIT_LIFECYCLE_DENIALS


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True)
class _Entry:
    request: PermitRequest
    permit_id: str | None
    expires_at: datetime


class PermitCache:
    """Permit ids keyed by caller permit idempotency key, with TTL and a cap.

    The TTL is the permit's own ``expires_at``: an entry read past its expiry
    is evicted and reported as a miss, so the wrapper resolves a fresh permit
    instead of invoking with one it knows is dead. ``maxsize`` bounds memory;
    past the cap the least recently used entry is evicted.
    """

    def __init__(
        self,
        maxsize: int = DEFAULT_MAXSIZE,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self._maxsize = maxsize
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def __len__(self) -> int:
        return len(self._entries)

    def _live(self, key: str) -> _Entry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._now():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry

    def _evict_overflow(self) -> None:
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    def get_request(self, key: str) -> PermitRequest | None:
        """The retained request body for ``key``, or None when absent/expired."""
        entry = self._live(key)
        return entry.request if entry is not None else None

    def store_request(self, key: str, request: PermitRequest) -> None:
        """Retain the exact request body sent under ``key`` for safe replay."""
        live = self._live(key)
        self._entries[key] = _Entry(
            request=request,
            permit_id=live.permit_id if live is not None else None,
            expires_at=_as_aware_utc(request.expires_at),
        )
        self._entries.move_to_end(key)
        self._evict_overflow()

    def get_permit_id(self, key: str) -> str | None:
        """The cached permit id for ``key``, or None when absent/expired."""
        entry = self._live(key)
        return entry.permit_id if entry is not None else None

    def store_permit(self, key: str, permit: Permit) -> bool:
        """Attach a created permit id to ``key``.

        Returns True when the permit is live and was kept. A permit that is
        already revoked, non-active, or past its expiry is dead on arrival:
        any stored id for ``key`` is cleared and False is returned, so the
        caller invokes once with the fresh id (letting the server denial
        surface) instead of caching a permit that can never succeed.
        """
        expires_at = _as_aware_utc(permit.expires_at)
        entry = self._entries.get(key)
        if permit.revoked_at is not None or permit.status != "active" or expires_at <= self._now():
            if entry is not None:
                entry.permit_id = None
            return False
        if entry is None:
            return False
        entry.permit_id = permit.permit_id
        entry.expires_at = expires_at
        self._entries.move_to_end(key)
        self._evict_overflow()
        return True

    def drop_permit(self, key: str) -> None:
        """Forget the cached permit id for ``key`` but keep its request body.

        Used when an invoke reports the permit revoked or expired: the next
        attempt re-sends the identical body, so the server replays the same
        denial instead of conflicting on a fresh timestamp.
        """
        entry = self._entries.get(key)
        if entry is not None:
            entry.permit_id = None


__all__ = [
    "DEFAULT_MAXSIZE",
    "PERMIT_LIFECYCLE_DENIALS",
    "PermitCache",
    "is_permit_lifecycle_denial",
]
