"""Public, non-secret build metadata for runtime health surfaces."""

from __future__ import annotations

import os
import re

from .config import get_settings


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def get_build_commit_sha() -> str | None:
    """Return a validated deployed Git SHA, or ``None`` when unavailable.

    Precedence (highest to lowest):
    1. ``RAILWAY_GIT_COMMIT_SHA`` — Railway's automatic deployment metadata
    2. ``BUILD_COMMIT_SHA`` — Docker build arg or explicit override

    Railway's git commit env is checked first so fresh deployment metadata
    always wins over stale service variables or cached build args.
    """

    candidates = (
        os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
        get_settings().BUILD_COMMIT_SHA,
    )
    for candidate in candidates:
        normalized = candidate.strip()
        if _GIT_SHA_RE.fullmatch(normalized):
            return normalized.lower()
    return None
