"""Optional error tracking (Sentry or compatible) behind an env DSN.

Tracking is off while SENTRY_DSN is empty, which is the default, so local
development and tests never phone home. When an operator sets the DSN, the
SDK is initialized once at startup and unhandled exceptions plus explicit
startup failures are reported there instead of landing only in stderr.

sentry-sdk is an optional import: the API boots and serves identically
without it installed, and error paths degrade to logging only.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_enabled = False


def init_error_tracking(
    dsn: str = "",
    environment: str = "local",
    release: str = "",
    traces_sample_rate: float = 0.0,
    **kwargs: Any,
) -> bool:
    """Initialize error tracking when a DSN is configured. Returns enabled."""
    global _enabled
    dsn = (dsn or "").strip()
    if not dsn:
        _enabled = False
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "error_tracking_unavailable: SENTRY_DSN is set but sentry-sdk "
            "is not installed; continuing with logs only"
        )
        _enabled = False
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        traces_sample_rate=traces_sample_rate,
        **kwargs,
    )
    _enabled = True
    logger.info("error_tracking_enabled", extra={"environment": environment})
    return True


def is_enabled() -> bool:
    """Whether error events are currently being reported anywhere."""
    return _enabled


def reset_for_tests() -> None:
    """Forget initialization state (tests only)."""
    global _enabled
    _enabled = False


def capture_exception(exc: BaseException) -> None:
    """Report a startup or background failure when tracking is enabled."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        logger.debug("error_tracking_capture_failed", exc_info=True)


def capture_message(message: str) -> None:
    """Report a non-exception alert when tracking is enabled."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message)
    except Exception:
        logger.debug("error_tracking_capture_failed", exc_info=True)
