"""One shared secret-handling standard for Pattern 11.

Every site that touches a credential follows the same three rules:

- secrets arrive from the environment (or a vault), never from argv,
  committed files, or hardcoded defaults, except clearly synthetic
  local-only defaults;
- secrets are masked in display and redacted in logs and error text;
- request/response models hold secrets as ``SecretStr`` so ``repr``,
  validation errors, and JSON dumps never carry the raw value.

This module is stdlib-only on purpose, so operator scripts can import it
without pulling the FastAPI import chain.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

REDACTED = "[secret]"

# Ported from the supplied jevlib strip_secrets. Redact before truncating.
SECRET_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"\b(sk|pk|rk)[-_](live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAIza[0-9A-Za-z_-]{30,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*\S+",
    r"\b[A-Fa-f0-9]{32,}\b",
    r"\b[A-Za-z0-9+/]{40,}={0,2}",
]

_SECRETS = [re.compile(pattern) for pattern in SECRET_PATTERNS]

SECRET_FIELD = re.compile(
    r"api[_-]?key|secret|token|password|passwd|pwd|authorization|credential|private[_-]?key",
    re.I,
)


def _unwrap(value: Any) -> str:
    """Return the raw string for ``str`` or ``SecretStr``-shaped values."""
    if value is None:
        return ""
    get_secret = getattr(value, "get_secret_value", None)
    if callable(get_secret):
        return str(get_secret())
    return str(value)


def redact_text(text: str, *, extra: tuple[str, ...] = ()) -> str:
    """Replace credential-shaped substrings with ``[secret]``.

    ``extra`` holds exact secret values known to the caller (for example a
    just-minted key); they are replaced literally before the patterns run.
    Use this on any string bound for logs, errors, or transcripts.
    """
    for secret in extra:
        if secret:
            text = text.replace(secret, REDACTED)
    for pattern in _SECRETS:
        text = pattern.sub(REDACTED, text)
    return text


def mask_secret(value: Any, *, prefix: int = 6, suffix: int = 4) -> str:
    """Short display form of a secret for logs and evidence.

    Shows a prefix and suffix with the middle removed, so an operator can
    match a key to its record without learning enough to reuse it.
    """
    raw = _unwrap(value)
    if not raw:
        return "<none>"
    if len(raw) <= prefix + suffix:
        return raw[:prefix] + "..." if len(raw) > prefix else raw
    return f"{raw[:prefix]}...{raw[-suffix:]}"


def resolve_secret(
    *,
    env_name: str,
    cli_value: str | None = None,
    description: str = "secret",
    required: bool = True,
) -> str:
    """Read a secret from the environment, never preferring argv.

    The environment wins when both are set. A command-line value still works
    for local-only use but prints a warning, because argv is visible in
    process listings and shell history. Raises ``SystemExit`` when the
    secret is required and neither source provides one.
    """
    from_env = (os.environ.get(env_name) or "").strip()
    if from_env:
        return from_env
    if cli_value and cli_value.strip():
        print(
            f"warning: prefer {env_name} env over the command-line flag "
            f"for {description} (argv is visible to local process listings)",
            file=sys.stderr,
        )
        return cli_value.strip()
    if required:
        raise SystemExit(f"error: set {env_name} in the environment for {description}")
    return ""
