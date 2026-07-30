from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


logger = logging.getLogger(__name__)


PRODUCTION_LIKE_ENVIRONMENTS = frozenset(
    {
        "prod",
        "production",
        "staging",
        "stage",
        "preprod",
        "pre-production",
        "preview",
    }
)

LOCAL_COMPATIBLE_ENVIRONMENTS = frozenset(
    {
        "",
        "ci",
        "dev",
        "development",
        "local",
        "localhost",
        "test",
        "testing",
    }
)


class TrustModeGuardrailError(RuntimeError):
    """Raised when trust mode is unsafe for a production-like deployment."""


def normalize_environment(environment: str | None) -> str:
    return (environment or "").strip().lower().replace("_", "-")


def is_production_like_environment(environment: str | None) -> bool:
    normalized = normalize_environment(environment)
    if normalized in LOCAL_COMPATIBLE_ENVIRONMENTS:
        return False
    return (
        normalized in PRODUCTION_LIKE_ENVIRONMENTS
        or normalized.startswith(("prod-", "production-", "staging-", "stage-"))
        or bool(normalized)
    )


def validate_trust_mode_config(
    *,
    environment: str | None,
    trust_mode_enabled: bool,
    signing_private_key_b64: str | None,
    allow_legacy_unpermitted_mcp: bool,
    debug: bool = False,
    webauthn_allow_mock: bool = False,
    enable_proof_surfaces: bool = True,
) -> None:
    """Refuse unsafe deploy postures in production-like environments.

    Trust-mode signing/legacy checks only apply when trust mode is enabled.
    DEBUG bootstrap, WebAuthn mock, and proof-surface mounts are always
    forbidden in production-like environments regardless of trust mode.
    """
    production_like = is_production_like_environment(environment)
    violations: list[str] = []

    if production_like:
        if debug:
            violations.append(
                "DEBUG must be false in production-like environments "
                "(DEBUG empty-key auth bootstrap is a deploy footgun)"
            )
        if webauthn_allow_mock:
            violations.append(
                "WEBAUTHN_ALLOW_MOCK must be false in production-like environments"
            )
        if enable_proof_surfaces:
            violations.append(
                "ENABLE_PROOF_SURFACES must be false in production-like "
                "environments (mount only CORE_TRUST_ROUTERS + MCP)"
            )

    if trust_mode_enabled and production_like:
        if not (signing_private_key_b64 or "").strip():
            violations.append(
                "TRUST_SIGNING_PRIVATE_KEY_B64 is required when "
                "TRUST_MODE_ENABLED=true in production-like environments"
            )
        if allow_legacy_unpermitted_mcp:
            violations.append(
                "ALLOW_LEGACY_UNPERMITTED_MCP must be false when "
                "TRUST_MODE_ENABLED=true in production-like environments"
            )

    if violations:
        raise TrustModeGuardrailError("; ".join(violations))


def validate_trust_mode_guardrails(settings: Settings) -> None:
    validate_trust_mode_config(
        environment=settings.ENVIRONMENT,
        trust_mode_enabled=settings.TRUST_MODE_ENABLED,
        signing_private_key_b64=settings.TRUST_SIGNING_PRIVATE_KEY_B64,
        allow_legacy_unpermitted_mcp=settings.ALLOW_LEGACY_UNPERMITTED_MCP,
        debug=settings.DEBUG,
        webauthn_allow_mock=settings.WEBAUTHN_ALLOW_MOCK,
        enable_proof_surfaces=settings.ENABLE_PROOF_SURFACES,
    )


def describe_permissive_trust_mode(
    *,
    trust_mode_enabled: bool,
    allow_legacy_unpermitted_mcp: bool,
) -> str | None:
    """Describe a permissive trust-mode posture, or return None when strict.

    The shipped defaults are `TRUST_MODE_ENABLED=true` and
    `ALLOW_LEGACY_UNPERMITTED_MCP=false`. Any deviation is an explicit
    operator opt-out and should be surfaced at startup so demos and
    incremental migrations cannot drift into permissive territory by
    accident.
    """
    if trust_mode_enabled and not allow_legacy_unpermitted_mcp:
        return None
    parts: list[str] = []
    if not trust_mode_enabled:
        parts.append("TRUST_MODE_ENABLED=false (no permit validation)")
    if allow_legacy_unpermitted_mcp:
        parts.append(
            "ALLOW_LEGACY_UNPERMITTED_MCP=true (ungoverned MCP calls accepted)"
        )
    return "; ".join(parts)


def warn_if_trust_mode_permissive(settings: Settings) -> None:
    """Log a loud warning when the trust plane is running in opt-out mode.

    Called once at startup, after `validate_trust_mode_guardrails`. In
    production-like environments the validator has already refused to boot
    under a permissive posture, so this only fires in local/dev/test
    environments that explicitly opted out — exactly when we want a visible
    reminder that ungoverned MCP calls are accepted.
    """
    description = describe_permissive_trust_mode(
        trust_mode_enabled=settings.TRUST_MODE_ENABLED,
        allow_legacy_unpermitted_mcp=settings.ALLOW_LEGACY_UNPERMITTED_MCP,
    )
    if description is None:
        return
    logger.warning(
        "trust_mode_permissive: %s. The trust plane is in legacy/opt-out "
        "mode; production deployments must set TRUST_MODE_ENABLED=true and "
        "ALLOW_LEGACY_UNPERMITTED_MCP=false.",
        description,
    )
