from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.trust_mode import (
    TrustModeGuardrailError,
    is_production_like_environment,
    validate_trust_mode_config,
    validate_trust_mode_guardrails,
)


@pytest.mark.parametrize(
    "environment",
    [
        "production",
        "prod",
        "staging",
        "stage",
        "preprod",
        "preview",
        "prod-us",
        "qa",
    ],
)
def test_classifier_marks_production_like_environments(environment: str):
    assert is_production_like_environment(environment)


@pytest.mark.parametrize(
    "environment",
    ["", "local", "development", "dev", "test", "testing", "ci", "localhost"],
)
def test_classifier_keeps_local_dev_test_compatible(environment: str):
    assert not is_production_like_environment(environment)
    validate_trust_mode_config(
        environment=environment,
        trust_mode_enabled=True,
        signing_private_key_b64="",
        allow_legacy_unpermitted_mcp=True,
    )


def test_production_trust_mode_requires_signing_private_key():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=False,
        )

    assert "TRUST_SIGNING_PRIVATE_KEY_B64" in str(exc_info.value)


def test_production_trust_mode_rejects_legacy_unpermitted_mcp():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64="private-key-material",
            allow_legacy_unpermitted_mcp=True,
        )

    assert "ALLOW_LEGACY_UNPERMITTED_MCP" in str(exc_info.value)


def test_production_trust_mode_reports_all_fail_closed_violations():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=True,
        )

    message = str(exc_info.value)
    assert "TRUST_SIGNING_PRIVATE_KEY_B64" in message
    assert "ALLOW_LEGACY_UNPERMITTED_MCP" in message


def test_production_without_trust_mode_stays_compatible():
    validate_trust_mode_config(
        environment="production",
        trust_mode_enabled=False,
        signing_private_key_b64="",
        allow_legacy_unpermitted_mcp=True,
    )


def test_settings_wrapper_uses_environment_field():
    settings = Settings(
        ENVIRONMENT="staging",
        TRUST_MODE_ENABLED=True,
        TRUST_SIGNING_PRIVATE_KEY_B64="private-key-material",
        ALLOW_LEGACY_UNPERMITTED_MCP=False,
    )

    validate_trust_mode_guardrails(settings)
