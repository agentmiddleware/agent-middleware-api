from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


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
) -> None:
    if not trust_mode_enabled or not is_production_like_environment(environment):
        return

    violations: list[str] = []
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
    )
