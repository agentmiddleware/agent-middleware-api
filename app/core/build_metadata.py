"""Public, non-secret build metadata for runtime health surfaces."""

from __future__ import annotations

import os
import re
from pathlib import Path


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_BUILD_SHA_FILE = Path("/app/.build_commit_sha")


def get_build_commit_sha() -> str | None:
    """Return a validated deployed Git SHA, or ``None`` when unavailable.

    Precedence (highest to lowest):
    1. ``RAILWAY_GIT_COMMIT_SHA`` — Railway's automatic deployment metadata
    2. ``/app/.build_commit_sha`` — SHA baked into image at build time
    3. ``None`` — Do not trust BUILD_COMMIT_SHA env (stale service variable)

    Railway's automatic env is checked first. The baked file is trusted when
    present. If neither exists, return None instead of reading BUILD_COMMIT_SHA
    from env to prevent stale COMMIT_SHA/BUILD_COMMIT_SHA service variables
    from winning.

    For local dev without Docker, set RAILWAY_GIT_COMMIT_SHA explicitly.
    """

    candidates = [
        os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
    ]
    
    # Read baked SHA file if it exists
    if _BUILD_SHA_FILE.exists():
        try:
            candidates.append(_BUILD_SHA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    
    # Do NOT read BUILD_COMMIT_SHA from env - it may be a stale service variable
    # If neither Railway env nor baked file is available, return None
    
    for candidate in candidates:
        normalized = candidate.strip()
        if _GIT_SHA_RE.fullmatch(normalized):
            return normalized.lower()
    return None
