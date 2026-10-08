"""GTM-03 API config/runtime honesty: dead dials, typo hints, boot posture.

Covers the trust_mode posture helpers and the VELOCITY_ALERT_THRESHOLD
deprecation added for the gtm-03-api-config-runtime slice.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.trust_mode import (
    TrustModeGuardrailError,
    describe_cors_wildcard,
    describe_human_approval_mode,
    is_production_like_environment,
    suggest_environment_name,
    validate_trust_mode_config,
)
from app.services.velocity_monitor import VelocityMonitor


def test_velocity_alert_threshold_is_deprecated_but_still_accepted():
    """The dead dial must warn, not break old env files."""
    field = Settings.model_fields["VELOCITY_ALERT_THRESHOLD"]
    assert field.deprecated, "VELOCITY_ALERT_THRESHOLD must stay deprecated"
    settings = Settings(_env_file=None, VELOCITY_ALERT_THRESHOLD=9)
    assert settings.VELOCITY_ALERT_THRESHOLD == 9


def test_velocity_monitor_no_longer_reads_the_dead_dial():
    """Nothing may treat the deprecated knob as a live control."""
    assert not hasattr(VelocityMonitor(), "_alert_threshold")


def test_velocity_freeze_threshold_is_still_the_live_control(monkeypatch):
    import app.services.velocity_monitor as velocity_monitor_module

    monkeypatch.setattr(
        velocity_monitor_module,
        "settings",
        Settings(_env_file=None, VELOCITY_FREEZE_THRESHOLD=5),
    )
    assert VelocityMonitor()._freeze_threshold == 5


@pytest.mark.parametrize(
    ("typo", "expected"),
    [
        ("prodution", "production"),
        ("PRODUTION", "production"),
        ("produciton", "production"),
        ("satging", "staging"),
        ("locl", "local"),
    ],
)
def test_suggest_environment_name_catches_typos(typo, expected):
    assert suggest_environment_name(typo) == expected


@pytest.mark.parametrize(
    "recognized",
    ["", "local", "dev", "production", "staging", "qa", "prod-us", "xyz123"],
)
def test_suggest_environment_name_silent_for_recognized_or_far_values(recognized):
    assert suggest_environment_name(recognized) is None


def test_guardrail_error_names_the_typo():
    """A typo'd ENVIRONMENT must say so instead of only listing violations."""
    with pytest.raises(TrustModeGuardrailError, match="did you mean 'production'"):
        validate_trust_mode_config(
            environment="prodution",
            trust_mode_enabled=True,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=False,
        )


def test_typo_hint_changes_no_classification():
    """The hint is messaging only: unknown values still fail closed."""
    assert is_production_like_environment("prodution")
    assert is_production_like_environment("qa")


def test_cors_wildcard_warns_only_on_production_like_boots():
    assert describe_cors_wildcard("*", "production") is not None
    assert "CORS_ORIGINS" in describe_cors_wildcard("*", "production")
    assert describe_cors_wildcard("*", "local") is None
    assert describe_cors_wildcard("https://app.example.com", "production") is None
    assert describe_cors_wildcard("", "production") is None


def test_approval_mode_names_simulation_locally():
    detail = describe_human_approval_mode(
        simulation_mode_human_approval=True, environment="local"
    )
    assert detail is not None
    assert "auto-approve" in detail
    assert "SENTINEL_API_URL" in detail and "SENTINEL_API_KEY" in detail


def test_approval_mode_says_simulation_fails_closed_in_production():
    detail = describe_human_approval_mode(
        simulation_mode_human_approval=True, environment="production"
    )
    assert detail is not None
    assert "fail closed" in detail


@pytest.mark.parametrize(
    ("url", "key", "missing"),
    [
        ("", "", "SENTINEL_API_URL and SENTINEL_API_KEY"),
        ("", "k", "SENTINEL_API_URL"),
        ("https://sentinel.example", "", "SENTINEL_API_KEY"),
    ],
)
def test_approval_mode_names_missing_sentinel_values(url, key, missing):
    detail = describe_human_approval_mode(
        simulation_mode_human_approval=False,
        sentinel_api_url=url,
        sentinel_api_key=key,
        environment="production",
    )
    assert detail is not None
    assert missing in detail


def test_approval_mode_silent_when_real_and_configured():
    assert (
        describe_human_approval_mode(
            simulation_mode_human_approval=False,
            sentinel_api_url="https://sentinel.example",
            sentinel_api_key="k",
            environment="production",
        )
        is None
    )
