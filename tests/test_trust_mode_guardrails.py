from __future__ import annotations

import logging

import pytest

from app.core.config import Settings
from app.core.trust_mode import (
    TrustModeGuardrailError,
    describe_permissive_trust_mode,
    is_production_like_environment,
    validate_trust_mode_config,
    validate_trust_mode_guardrails,
    warn_if_trust_mode_permissive,
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


def test_describe_permissive_returns_none_when_strict():
    assert (
        describe_permissive_trust_mode(
            trust_mode_enabled=True,
            allow_legacy_unpermitted_mcp=False,
        )
        is None
    )


@pytest.mark.parametrize(
    ("trust_mode_enabled", "allow_legacy_unpermitted_mcp", "expected_fragments"),
    [
        (False, False, ["TRUST_MODE_ENABLED=false"]),
        (True, True, ["ALLOW_LEGACY_UNPERMITTED_MCP=true"]),
        (
            False,
            True,
            ["TRUST_MODE_ENABLED=false", "ALLOW_LEGACY_UNPERMITTED_MCP=true"],
        ),
    ],
)
def test_describe_permissive_lists_each_opt_out(
    trust_mode_enabled: bool,
    allow_legacy_unpermitted_mcp: bool,
    expected_fragments: list[str],
):
    description = describe_permissive_trust_mode(
        trust_mode_enabled=trust_mode_enabled,
        allow_legacy_unpermitted_mcp=allow_legacy_unpermitted_mcp,
    )
    assert description is not None
    for fragment in expected_fragments:
        assert fragment in description


class _ListHandler(logging.Handler):
    """Minimal handler that collects records into a list.

    Used in place of caplog because structlog reconfiguration earlier in the
    test suite can disable propagation on `app.core.trust_mode`, which would
    make caplog miss our records when the test runs as part of the full
    suite (it still works in isolation).
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capture_trust_mode_warnings(callable_):
    target = logging.getLogger("app.core.trust_mode")
    handler = _ListHandler()
    prior_level = target.level
    prior_disabled = target.disabled
    prior_propagate = target.propagate
    target.addHandler(handler)
    target.setLevel(logging.WARNING)
    target.disabled = False
    target.propagate = True
    try:
        callable_()
    finally:
        target.removeHandler(handler)
        target.setLevel(prior_level)
        target.disabled = prior_disabled
        target.propagate = prior_propagate
    return handler.records


def test_warn_if_trust_mode_permissive_logs_warning_in_legacy_mode():
    settings = Settings(
        TRUST_MODE_ENABLED=False,
        ALLOW_LEGACY_UNPERMITTED_MCP=True,
    )
    records = _capture_trust_mode_warnings(
        lambda: warn_if_trust_mode_permissive(settings)
    )
    assert any(
        "trust_mode_permissive" in record.getMessage() for record in records
    ), records


def test_warn_if_trust_mode_permissive_silent_when_strict():
    settings = Settings(
        TRUST_MODE_ENABLED=True,
        ALLOW_LEGACY_UNPERMITTED_MCP=False,
    )
    records = _capture_trust_mode_warnings(
        lambda: warn_if_trust_mode_permissive(settings)
    )
    assert all(
        "trust_mode_permissive" not in record.getMessage() for record in records
    ), records


def test_shipped_defaults_are_strict():
    """The shipped product defaults must be strict trust mode.

    This is the pitch-critical invariant: a fresh deployment with no env
    overrides should reject ungoverned MCP calls. The test suite opts back
    into legacy via tests/conftest.py env vars, so this constructs Settings
    in isolation to assert the *application* default rather than the
    test-runtime override.
    """
    settings = Settings(
        TRUST_MODE_ENABLED=True,
        ALLOW_LEGACY_UNPERMITTED_MCP=False,
    )
    assert settings.TRUST_MODE_ENABLED is True
    assert settings.ALLOW_LEGACY_UNPERMITTED_MCP is False
    # And confirm the model fields' declared defaults match (independent of
    # any env override the test runtime may have applied).
    field_defaults = {
        name: field.default
        for name, field in Settings.model_fields.items()
        if name in {"TRUST_MODE_ENABLED", "ALLOW_LEGACY_UNPERMITTED_MCP"}
    }
    assert field_defaults == {
        "TRUST_MODE_ENABLED": True,
        "ALLOW_LEGACY_UNPERMITTED_MCP": False,
    }
