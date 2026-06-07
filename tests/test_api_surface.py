from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.api_surface import (
    ApiSurfaceModeError,
    api_surface_status,
    normalize_api_surface_mode,
    proof_surfaces_enabled,
)


def _settings(mode: str):
    return SimpleNamespace(API_SURFACE_MODE=mode)


def test_trust_plane_mode_disables_proof_surfaces():
    settings = _settings("trust_plane")

    assert normalize_api_surface_mode(settings.API_SURFACE_MODE) == "trust_plane"
    assert proof_surfaces_enabled(settings) is False
    assert api_surface_status(settings) == {
        "mode": "trust_plane",
        "proof_surfaces_enabled": False,
        "mounted_surface": "trust_plane",
    }


def test_full_mode_enables_proof_surfaces():
    settings = _settings("full")

    assert normalize_api_surface_mode(settings.API_SURFACE_MODE) == "full"
    assert proof_surfaces_enabled(settings) is True
    assert api_surface_status(settings) == {
        "mode": "full",
        "proof_surfaces_enabled": True,
        "mounted_surface": "full",
    }


def test_invalid_mode_raises_clear_error():
    with pytest.raises(ApiSurfaceModeError, match="API_SURFACE_MODE"):
        normalize_api_surface_mode("everything")
