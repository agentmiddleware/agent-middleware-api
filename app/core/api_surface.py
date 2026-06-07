"""API surface selection for paid-pilot trust-plane deployments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config import Settings


ApiSurfaceMode = Literal["trust_plane", "full"]

TRUST_PLANE_MODE: ApiSurfaceMode = "trust_plane"
FULL_MODE: ApiSurfaceMode = "full"
_VALID_MODES = {TRUST_PLANE_MODE, FULL_MODE}


class ApiSurfaceModeError(RuntimeError):
    """Raised when API_SURFACE_MODE is not one of the supported modes."""


def normalize_api_surface_mode(value: str | None) -> ApiSurfaceMode:
    normalized = (value or TRUST_PLANE_MODE).strip().lower().replace("-", "_")
    if normalized not in _VALID_MODES:
        raise ApiSurfaceModeError("API_SURFACE_MODE must be one of: full, trust_plane")
    return normalized


def proof_surfaces_enabled(settings: Settings) -> bool:
    return normalize_api_surface_mode(settings.API_SURFACE_MODE) == FULL_MODE


def api_surface_status(settings: Settings) -> dict[str, str | bool]:
    mode = normalize_api_surface_mode(settings.API_SURFACE_MODE)
    proof_enabled = mode == FULL_MODE
    return {
        "mode": mode,
        "proof_surfaces_enabled": proof_enabled,
        "mounted_surface": "full" if proof_enabled else "trust_plane",
    }
