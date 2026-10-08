"""In-process operational request counters for pilot monitoring.

A pilot operator needs one dashboardable signal: how many requests the
gateway served, how many failed, and how slow the paths are. This module
holds those counters in process memory behind a lock. The request-ID
middleware records every request here, and ``GET /metrics`` serves a
snapshot.

The counters are deliberately process-local: each worker keeps its own,
and every value resets on restart. The snapshot says so explicitly, so an
operator graphing it is not surprised by a deploy. Exporting to durable
storage is future work, not a silent property.
"""

from __future__ import annotations

import threading
import time

# Route templates are bounded (one entry per mounted route), but a raw
# request path can carry unbounded values such as wallet IDs. Cap the table
# so a hostile or merely varied path space cannot grow memory without limit.
_MAX_ROUTE_ENTRIES = 500
_OVERFLOW_ROUTE_KEY = "OTHER"
_METRICS_PATH = "/metrics"

_lock = threading.Lock()
_process_started_at = time.time()
_requests_total = 0
_errors_total = 0
# key: "METHOD /path-template" -> {"requests": int, "errors": int,
# "latency_sum_seconds": float}
_routes: dict[str, dict[str, float]] = {}


def _route_key(route_template: str | None, method: str, raw_path: str) -> str:
    template = route_template or raw_path
    return f"{method.upper()} {template}"


def record_request(
    *,
    route_template: str | None,
    method: str,
    raw_path: str,
    status_code: int,
    latency_seconds: float,
) -> None:
    """Count one finished request, including requests that raised."""
    if raw_path == _METRICS_PATH:
        # Scraping the metrics endpoint must not move the counters it reads.
        return
    key = _route_key(route_template, method, raw_path)
    failed = status_code >= 500
    with _lock:
        global _requests_total, _errors_total
        _requests_total += 1
        if failed:
            _errors_total += 1
        entry = _routes.get(key)
        if entry is None:
            if len(_routes) >= _MAX_ROUTE_ENTRIES:
                key = _OVERFLOW_ROUTE_KEY
                entry = _routes.get(key)
            if entry is None:
                entry = {"requests": 0, "errors": 0, "latency_sum_seconds": 0.0}
                _routes[key] = entry
        entry["requests"] += 1
        if failed:
            entry["errors"] += 1
        entry["latency_sum_seconds"] += max(0.0, latency_seconds)


def get_metrics_snapshot() -> dict:
    """Return a JSON-serializable snapshot of the current counters."""
    now = time.time()
    with _lock:
        routes = {
            key: {
                "requests": int(entry["requests"]),
                "errors": int(entry["errors"]),
                "latency_sum_seconds": entry["latency_sum_seconds"],
                "latency_avg_seconds": (
                    entry["latency_sum_seconds"] / entry["requests"]
                    if entry["requests"]
                    else 0.0
                ),
            }
            for key, entry in sorted(_routes.items())
        }
        return {
            "requests_total": _requests_total,
            "errors_total": _errors_total,
            "uptime_seconds": now - _process_started_at,
            "routes": routes,
            "scope_note": (
                "Process-local counters: each worker keeps its own and all "
                "values reset on restart. Do not sum across deploys."
            ),
        }


def reset_metrics() -> None:
    """Clear all counters. Tests only; never call in serving code."""
    with _lock:
        global _requests_total, _errors_total
        _requests_total = 0
        _errors_total = 0
        _routes.clear()
