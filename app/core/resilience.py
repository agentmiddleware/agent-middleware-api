"""
Resilience utilities for retry with backoff and circuit breakers.
"""

import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    retriable_exceptions: tuple = (Exception,),
):
    """
    Decorator for async functions with exponential backoff retry.

    Args:
        max_attempts: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay between retries.
        exponential_base: Base for exponential backoff.
        retriable_exceptions: Tuple of exception types to retry on.

    Usage:
        @retry_with_backoff(max_attempts=3, base_delay=1.0)
        async def call_api():
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retriable_exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.warning(
                            "retry_exhausted: %s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            str(e),
                        )
                        raise

                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)), max_delay
                    )
                    logger.info(
                        "retry_attempt: %s attempt %d/%d, delay=%.2fs: %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        delay,
                        str(e),
                    )
                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception

        return wrapper

    return decorator


class CircuitBreaker:
    """
    Simple circuit breaker implementation.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Circuit is tripped, requests fail fast
    - HALF_OPEN: Testing if service recovered
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if (
                self._last_failure_time
                and time.monotonic() - self._last_failure_time >= self._recovery_timeout
            ):
                self._state = self.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def record_success(self):
        """Record a successful call."""
        if self._state == self.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self._half_open_max_calls:
                self._state = self.CLOSED
                self._failure_count = 0
                logger.info("circuit_breaker_closed: recovery_successful")
        elif self._state == self.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self):
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            logger.warning("circuit_breaker_reopened: half_open_failure")
        elif self._failure_count >= self._failure_threshold:
            self._state = self.OPEN
            logger.warning(
                "circuit_breaker_opened: threshold_exceeded, failures=%d",
                self._failure_count,
            )

    def is_allowed(self) -> bool:
        """Check if a call is allowed through the circuit breaker."""
        state = self.state
        if state == self.CLOSED:
            return True
        if state == self.HALF_OPEN:
            return self._half_open_calls < self._half_open_max_calls
        return False  # OPEN

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a function through the circuit breaker."""
        if not self.is_allowed():
            raise CircuitBreakerOpen(f"Circuit breaker is {self.state}")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""

    pass
