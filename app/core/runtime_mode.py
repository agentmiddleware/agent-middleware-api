"""
Per-service simulation mode registry.

Every service whose production behavior still depends on mocks, synthetic
data, or hardcoded responses gates its real-vs-simulated branch through
``is_simulation("<service>")``. Flipping a flag to ``False`` is the signal
that a real integration is wired up and callers expect real side effects.

See issue #26 and the tracking issue #40 for context.
"""

from __future__ import annotations

from .config import get_settings


# Service name -> Settings attribute.
# Adding a service here without also adding the Settings field will raise
# at startup on first lookup — intentional, so drift is loud.
_SERVICE_TO_SETTING: dict[str, str] = {
    "oracle": "SIMULATION_MODE_ORACLE",
    "red_team": "SIMULATION_MODE_RED_TEAM",
    "rtaas": "SIMULATION_MODE_RTAAS",
    "media_engine": "SIMULATION_MODE_MEDIA_ENGINE",
    "iot_bridge": "SIMULATION_MODE_IOT_BRIDGE",
    "telemetry_pm": "SIMULATION_MODE_TELEMETRY_PM",
    "agent_comms": "SIMULATION_MODE_AGENT_COMMS",
    "content_factory": "SIMULATION_MODE_CONTENT_FACTORY",
}


SERVICE_NAMES: frozenset[str] = frozenset(_SERVICE_TO_SETTING.keys())


class UnknownServiceError(ValueError):
    """Raised when a service name isn't registered for simulation mode."""


def is_simulation(service: str) -> bool:
    """Return whether the named service is running in simulation mode."""
    attr = _SERVICE_TO_SETTING.get(service)
    if attr is None:
        raise UnknownServiceError(
            f"Unknown service '{service}'. Known: {sorted(SERVICE_NAMES)}"
        )
    return bool(getattr(get_settings(), attr))


def require_simulation(service: str, issue: str | None = None) -> None:
    """
    Guard used at the top of a simulated method while the real
    implementation is still pending. Raises NotImplementedError if the
    service's simulation flag was disabled — surfaces a loud failure
    instead of silently running a stub against production traffic.
    """
    if not is_simulation(service):
        suffix = f" (tracking: {issue})" if issue else ""
        raise NotImplementedError(
            f"{service}: real implementation pending{suffix}. "
            f"Set SIMULATION_MODE_{service.upper()}=true until it lands."
        )


def get_simulation_modes() -> dict[str, bool]:
    """Snapshot of every service's simulation state. Used by health checks."""
    return {name: is_simulation(name) for name in sorted(SERVICE_NAMES)}
