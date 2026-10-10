"""Shared marker for money-moving routes.

Foundational guard for the class where idempotency keys are optional on
money writes, so a normal network retry can charge twice. Every FastAPI
route that moves money must carry the ``@requires_idempotency`` marker.
The marker changes no route behavior. It only records, in one registry,
whether the route already enforces a client key today, so the gap list
cannot silently grow. ``tests/test_idempotency_gate.py`` fails if any
covered money route lacks the marker.

``enforced`` means a retry cannot repeat the money effect. That holds
when the route requires a client ``Idempotency-Key``, and it also holds
for routes that are safe by construction (a disabled endpoint that
never writes the ledger, or a provider webhook deduped on the provider
event id). Routes with ``enforced=False`` accept a retry as a new money
movement and are tracked as xfail entries in the gate test until a
follow-up requires the key.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

MARKER_ATTR = "__idempotency_gate__"

MONEY_ROUTE_REGISTRY: dict[str, dict[str, Any]] = {}


def requires_idempotency(
    route_key: str, *, enforced: bool, mechanism: str
) -> Callable[[F], F]:
    """Tag a money-moving endpoint without changing its behavior.

    Args:
        route_key: Stable ``"METHOD /full/path"`` label, used as the
            registry key and matched by the gate test.
        enforced: True when a retry cannot repeat the money effect.
        mechanism: Plain-English note saying how (required header,
            optional header, provider dedupe, or disabled endpoint).
    """

    def decorator(fn: F) -> F:
        record = {
            "route_key": route_key,
            "enforced": enforced,
            "mechanism": mechanism,
            "endpoint": fn.__name__,
        }
        setattr(fn, MARKER_ATTR, record)
        MONEY_ROUTE_REGISTRY[route_key] = record
        return fn

    return decorator


def marker_of(fn: Any) -> dict[str, Any] | None:
    """Return the marker record for an endpoint, or None if unmarked."""
    return getattr(fn, MARKER_ATTR, None)
