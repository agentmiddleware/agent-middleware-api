"""Minimal process-local HTTP metrics for the /metrics endpoint.

These counters answer "how much traffic, how many errors, how slow" per
route without adding a dependency. They are deliberately process-local:
every value resets on restart (each series is labeled as such in the
exposition), so an operator graphing them across deploys must expect the
counters to drop to zero. Durable history is a future export to the state
backend, not a silent property of these numbers.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# (route, status_code) -> count
_request_counts: dict[tuple[str, str], int] = {}
# route -> [total_seconds, count] for average latency
_latency_totals: dict[str, list[float]] = {}
_started_at = time.time()


def record_request(route: str, status_code: int, duration_seconds: float) -> None:
    """Count one completed response and fold its latency into the average."""
    key = (route or "unknown", str(status_code))
    with _lock:
        _request_counts[key] = _request_counts.get(key, 0) + 1
        totals = _latency_totals.setdefault(key[0], [0.0, 0.0])
        totals[0] += max(duration_seconds, 0.0)
        totals[1] += 1


def reset_metrics() -> None:
    """Clear all counters (tests only)."""
    with _lock:
        _request_counts.clear()
        _latency_totals.clear()


def snapshot() -> dict[str, object]:
    """Return a point-in-time copy of the counters."""
    with _lock:
        return {
            "requests": dict(_request_counts),
            "latency": {k: list(v) for k, v in _latency_totals.items()},
            "uptime_seconds": time.time() - _started_at,
        }


def render_prometheus_text() -> str:
    """Render the counters in Prometheus text exposition format."""
    lines = [
        "# HELP amw_http_requests_total HTTP responses by route and status. Process-local, resets on restart.",
        "# TYPE amw_http_requests_total counter",
    ]
    with _lock:
        items = sorted(_request_counts.items())
        latencies = {k: list(v) for k, v in _latency_totals.items()}
        uptime = time.time() - _started_at
    for (route, status), count in items:
        lines.append(
            f'amw_http_requests_total{{route="{route}",status="{status}"}} {count}'
        )
    lines += [
        "# HELP amw_http_request_latency_seconds_avg Average response latency by route. Process-local, resets on restart.",
        "# TYPE amw_http_request_latency_seconds_avg gauge",
    ]
    for route in sorted(latencies):
        total, count = latencies[route]
        avg = total / count if count else 0.0
        lines.append(
            f'amw_http_request_latency_seconds_avg{{route="{route}"}} {avg:.6f}'
        )
    lines += [
        "# HELP amw_process_uptime_seconds Seconds since this process started counting.",
        "# TYPE amw_process_uptime_seconds gauge",
        f"amw_process_uptime_seconds {uptime:.1f}",
    ]
    return "\n".join(lines) + "\n"
