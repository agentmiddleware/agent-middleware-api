"""Public, non-secret build metadata for runtime health surfaces."""

from __future__ import annotations

import os
import re

from .config import get_settings


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def get_build_commit_sha() -> str | None:
    """Return a validated deployed Git SHA, or ``None`` when unavailable.

    ``BUILD_COMMIT_SHA`` is the portable explicit setting. Railway's deployment
    metadata variable is accepted as a fallback so the runtime can report the
    exact source revision without copying it into application secrets.
    """

    candidates = (
        get_settings().BUILD_COMMIT_SHA,
        os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
    )
    for candidate in candidates:
        normalized = candidate.strip()
        if _GIT_SHA_RE.fullmatch(normalized):
            return normalized.lower()
    return None
