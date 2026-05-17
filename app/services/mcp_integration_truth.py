"""
MCP tool honesty metadata (Phase 0).

Maps each tool's billing ``category`` to runtime simulation state so
``/mcp/tools.json`` stays aligned with ``/health/dependencies`` ``simulation_modes``.
"""

from __future__ import annotations

from typing import Any, Literal

from ..core.runtime_mode import SERVICE_NAMES, is_simulation

IntegrationStatus = Literal["simulated", "integrated", "platform"]


def truth_for_category(category: str) -> dict[str, Any]:
    """
    Return stable annotation fields for MCP tool manifests.

    - ``simulated`` / ``integrated``: category is a gated runtime pillar
    - ``platform``: billing, sandbox, protocol helpers, etc. (no SIMULATION_MODE flag)
    """
    if category in SERVICE_NAMES:
        sim = is_simulation(category)
        status: IntegrationStatus = "simulated" if sim else "integrated"
        return {
            "simulation": sim,
            "integration_status": status,
            "runtime_service": category,
        }
    return {
        "simulation": False,
        "integration_status": "platform",
        "runtime_service": None,
    }
