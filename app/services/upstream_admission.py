"""Per-process concurrency limit and circuit breaker for upstream MCP dispatch.

Both controls are off unless configured. A limit of ``0`` does not cap
concurrency. The breaker, when enabled, shares one ``CircuitBreaker`` per
upstream key inside this process. Neither control is coordinated across
processes or hosts: each worker has its own semaphores and failure counts.

The concurrency slot is an ``asyncio.Semaphore``. Callers fail immediately
when it is exhausted; they do not queue. The slot is released by
``UpstreamAdmissionSlot.close``, which is synchronous so a cancellation
cannot skip it by landing on an await.
"""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.config import Settings, get_settings
from ..core.resilience import CircuitBreaker

# The adapter reports a transport failure or timeout before the dispatch
# checkpoint with this code. Later delivery_uncertain outcomes are recorded
# separately and do not use this string.
PRE_DISPATCH_TRANSPORT_FAILURE_CODE = "upstream_pre_dispatch_failed"

# Hint returned when the process semaphore is full. The slot may free sooner;
# this is not a scheduled delay.
SATURATED_RETRY_AFTER_SECONDS = 1

# One probe at a time once the breaker has waited out its recovery window.
_HALF_OPEN_PROBES = 1


def upstream_admission_key(service: Mapping[str, Any]) -> str:
    """Key the limit and the breaker by upstream base URL, else server id.

    The base URL is ``upstream_origin`` with one trailing slash removed so
    ``https://partner.example`` and ``https://partner.example/`` share a
    semaphore. When the origin is missing, the registered ``service_id`` is
    the key.
    """
    origin = str(service.get("upstream_origin") or "").strip().rstrip("/")
    if origin:
        return origin
    service_id = str(service.get("service_id") or "").strip()
    if service_id:
        return service_id
    return "upstream"


def upstream_limits_enabled(settings: Settings | None = None) -> bool:
    """True when either control would change an upstream call."""
    current = settings if settings is not None else get_settings()
    return bool(
        current.UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM > 0
        or current.UPSTREAM_CIRCUIT_BREAKER_ENABLED
    )


@dataclass(frozen=True)
class UpstreamAdmissionRefusal:
    """The call must not reserve, debit, or dispatch."""

    reason: str
    retry_after_seconds: int


class UpstreamAdmissionSlot:
    """One admitted call's semaphore hold and optional breaker probe."""

    def __init__(
        self,
        gate: UpstreamAdmissionGate,
        key: str,
        semaphore: asyncio.Semaphore | None,
        *,
        half_open_probe: bool,
        generation: int,
    ) -> None:
        self._gate = gate
        self.key = key
        self._semaphore = semaphore
        self._half_open_probe = half_open_probe
        self._generation = generation
        self._observed = False
        self._closed = False

    def observe_success(self) -> None:
        """The upstream answered. Only a half-open probe can close the breaker."""
        self._gate.observe(self, failure=False)

    def observe_failure(self) -> None:
        """Count one transport failure or delivery_uncertain outcome.

        Recording the failure does not decide the call. The router keeps the
        outcome it already chose.
        """
        self._gate.observe(self, failure=True)

    def close(self) -> None:
        """Release the semaphore and any half-open probe. Idempotent and sync."""
        self._gate.close_slot(self)


class UpstreamAdmissionGate:
    """Process-local semaphores and breakers keyed by upstream identity."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._semaphores: dict[str, tuple[int, asyncio.Semaphore]] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._half_open_inflight: dict[str, int] = {}
        # Bumped when a counted outcome opens the breaker. Slots admitted
        # earlier keep the old generation, so their later results cannot
        # close or reopen the half-open trial.
        self._breaker_generation: dict[str, int] = {}

    def clear(self) -> None:
        """Drop process-local state. Tests use this between cases."""
        with self._lock:
            self._semaphores.clear()
            self._breakers.clear()
            self._half_open_inflight.clear()
            self._breaker_generation.clear()

    def try_admit(self, key: str) -> UpstreamAdmissionSlot | UpstreamAdmissionRefusal:
        """Admit one call, or refuse before the caller reserves anything.

        An open breaker refuses first, so a saturated semaphore is not held
        by a call the breaker would reject. A half-open breaker admits one
        probe. The semaphore acquire does not wait.
        """
        settings = get_settings()
        limit = settings.UPSTREAM_MAX_CONCURRENCY_PER_UPSTREAM
        with self._lock:
            half_open_probe = False
            if settings.UPSTREAM_CIRCUIT_BREAKER_ENABLED:
                breaker = self._breaker_locked(key, settings)
                state = breaker.state
                if state == CircuitBreaker.OPEN:
                    return UpstreamAdmissionRefusal(
                        "upstream_circuit_open",
                        _retry_after_seconds(breaker),
                    )
                if state == CircuitBreaker.HALF_OPEN:
                    inflight = self._half_open_inflight.get(key, 0)
                    if inflight >= _HALF_OPEN_PROBES:
                        return UpstreamAdmissionRefusal(
                            "upstream_circuit_open",
                            SATURATED_RETRY_AFTER_SECONDS,
                        )
                    self._half_open_inflight[key] = inflight + 1
                    half_open_probe = True
            semaphore: asyncio.Semaphore | None = None
            if limit > 0:
                semaphore = self._semaphore_locked(key, limit)
                if not _try_acquire(semaphore):
                    if half_open_probe:
                        self._release_half_open_probe_locked(key)
                    return UpstreamAdmissionRefusal(
                        "upstream_concurrency_saturated",
                        SATURATED_RETRY_AFTER_SECONDS,
                    )
            return UpstreamAdmissionSlot(
                self,
                key,
                semaphore,
                half_open_probe=half_open_probe,
                generation=self._breaker_generation.get(key, 0),
            )

    def observe(self, slot: UpstreamAdmissionSlot, *, failure: bool) -> None:
        """Count one outcome, unless it would override the half-open trial.

        Calls admitted before the breaker opened keep that generation. Once
        a counted outcome opens the breaker, those calls can still finish,
        but their success or failure is not recorded. While the breaker is
        half-open, only the slot admitted as the probe may close it or
        open it again.
        """
        with self._lock:
            if slot._observed:
                return
            slot._observed = True
            if not get_settings().UPSTREAM_CIRCUIT_BREAKER_ENABLED:
                return
            breaker = self._breakers.get(slot.key)
            if breaker is None or not self._observation_counts_locked(slot, breaker):
                return
            state_before = breaker._state
            if failure:
                breaker.record_failure()
            else:
                breaker.record_success()
            if (
                state_before != CircuitBreaker.OPEN
                and breaker._state == CircuitBreaker.OPEN
            ):
                self._breaker_generation[slot.key] = slot._generation + 1

    def _observation_counts_locked(
        self, slot: UpstreamAdmissionSlot, breaker: CircuitBreaker
    ) -> bool:
        # A pre-open call is stale even if this read has not yet moved OPEN
        # to HALF_OPEN. Skip it before ``state`` so it cannot start the trial.
        if (
            not slot._half_open_probe
            and slot._generation != self._breaker_generation.get(slot.key, 0)
        ):
            return False
        # ``state`` may move OPEN to HALF_OPEN once the recovery window
        # has elapsed. Only the designated probe may record after that.
        if breaker.state == CircuitBreaker.HALF_OPEN:
            return slot._half_open_probe
        return True

    def close_slot(self, slot: UpstreamAdmissionSlot) -> None:
        with self._lock:
            if slot._closed:
                return
            slot._closed = True
            if slot._semaphore is not None:
                slot._semaphore.release()
            if slot._half_open_probe:
                self._release_half_open_probe_locked(slot.key)

    def _breaker_locked(self, key: str, settings: Settings) -> CircuitBreaker:
        threshold = settings.UPSTREAM_CIRCUIT_BREAKER_FAILURE_THRESHOLD
        recovery = float(settings.UPSTREAM_CIRCUIT_BREAKER_RECOVERY_SECONDS)
        current = self._breakers.get(key)
        inflight = self._half_open_inflight.get(key, 0)
        if current is not None and (
            inflight > 0
            or (
                current._failure_threshold == threshold
                and current._recovery_timeout == recovery
            )
        ):
            return current
        current = CircuitBreaker(
            failure_threshold=threshold,
            recovery_timeout=recovery,
            half_open_max_calls=_HALF_OPEN_PROBES,
        )
        self._breakers[key] = current
        return current

    def _semaphore_locked(self, key: str, limit: int) -> asyncio.Semaphore:
        cached = self._semaphores.get(key)
        if cached is not None:
            cached_limit, semaphore = cached
            if cached_limit == limit or semaphore._value != cached_limit:
                return semaphore
        semaphore = asyncio.Semaphore(limit)
        self._semaphores[key] = (limit, semaphore)
        return semaphore

    def _release_half_open_probe_locked(self, key: str) -> None:
        inflight = self._half_open_inflight.get(key, 0)
        if inflight <= 1:
            self._half_open_inflight.pop(key, None)
        else:
            self._half_open_inflight[key] = inflight - 1


def _try_acquire(semaphore: asyncio.Semaphore) -> bool:
    """Take one permit without waiting.

    ``Semaphore.acquire`` parks when the counter is zero. This matches its
    fast path (counter > 0 and nobody queued) and otherwise returns False.
    This gate never queues a waiter.
    """
    if semaphore.locked():
        return False
    semaphore._value -= 1
    return True


def _retry_after_seconds(breaker: CircuitBreaker) -> int:
    remaining = breaker.recovery_remaining_seconds()
    if remaining <= 0:
        return SATURATED_RETRY_AFTER_SECONDS
    return max(1, math.ceil(remaining))


_gate = UpstreamAdmissionGate()


def get_upstream_admission_gate() -> UpstreamAdmissionGate:
    return _gate


def clear_upstream_admission_state() -> None:
    _gate.clear()
