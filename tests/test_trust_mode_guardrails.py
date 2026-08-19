from __future__ import annotations

import base64
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


VALID_SIGNING_PRIVATE_KEY_B64 = base64.b64encode(bytes(range(32))).decode()
VALID_PRODUCTION_DATABASE_URL = "postgresql+asyncpg://user:pw@db.internal:5432/trust"


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


@pytest.mark.parametrize(
    "signing_private_key_b64",
    ["not-base64!", base64.b64encode(b"too-short").decode()],
)
def test_production_trust_mode_rejects_invalid_signing_private_key_material(
    signing_private_key_b64: str,
):
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=signing_private_key_b64,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
        )

    assert "valid 32-byte Ed25519 private key" in str(exc_info.value)


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


@pytest.mark.parametrize("allow_legacy_unpermitted_mcp", [False, True])
def test_production_rejects_disabled_trust_mode(
    allow_legacy_unpermitted_mcp: bool,
):
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=False,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=allow_legacy_unpermitted_mcp,
            enable_proof_surfaces=False,
            debug=False,
            webauthn_allow_mock=False,
        )

    assert "TRUST_MODE_ENABLED" in str(exc_info.value)


def test_production_rejects_debug_webauthn_mock_and_proof_surfaces():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=False,
            signing_private_key_b64="",
            allow_legacy_unpermitted_mcp=True,
            debug=True,
            webauthn_allow_mock=True,
            enable_proof_surfaces=True,
        )

    message = str(exc_info.value)
    assert "DEBUG" in message
    assert "WEBAUTHN_ALLOW_MOCK" in message
    assert "ENABLE_PROOF_SURFACES" in message


def test_settings_wrapper_uses_environment_field():
    settings = Settings(
        ENVIRONMENT="staging",
        TRUST_MODE_ENABLED=True,
        TRUST_SIGNING_PRIVATE_KEY_B64=VALID_SIGNING_PRIVATE_KEY_B64,
        ALLOW_LEGACY_UNPERMITTED_MCP=False,
        ENABLE_PROOF_SURFACES=False,
        ENABLE_DEV_KEY_SELF_PROVISION=False,
        DEBUG=False,
        WEBAUTHN_ALLOW_MOCK=False,
        DATABASE_URL=VALID_PRODUCTION_DATABASE_URL,
    )

    validate_trust_mode_guardrails(settings)


def test_public_mcp_requires_shared_rate_limiter_in_production():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            enable_public_mcp_endpoint=True,
            redis_url="",
            public_url="https://api.example.com",
        )

    assert "REDIS_URL" in str(exc_info.value)


def test_public_mcp_accepts_shared_rate_limiter_in_production():
    validate_trust_mode_config(
        environment="production",
        trust_mode_enabled=True,
        signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
        allow_legacy_unpermitted_mcp=False,
        enable_proof_surfaces=False,
        enable_public_mcp_endpoint=True,
        redis_url="redis://redis.internal:6379/0",
        public_url="https://api.example.com",
        database_url=VALID_PRODUCTION_DATABASE_URL,
    )


def test_public_mcp_requires_public_origin_in_production():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            enable_public_mcp_endpoint=True,
            redis_url="redis://redis.internal:6379/0",
            public_url="",
        )

    assert "PUBLIC_URL" in str(exc_info.value)



@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///./trust.db",
        "sqlite:///./trust.db",
        "SQLite+aiosqlite:///./trust.db",
        "sqlite+aiosqlite:///:memory:",
    ],
)
def test_production_refuses_a_sqlite_database_url(database_url: str):
    """SQLite in production is refused at boot, not discovered under load.

    SQLAlchemy silently drops ``SELECT ... FOR UPDATE`` on SQLite, so every
    guarded money and permit path loses the serialization it is written to
    rely on. The in-memory spellings are refused too: they are no safer, and
    they additionally lose the ledger on restart.
    """
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            database_url=database_url,
        )

    message = str(exc_info.value)
    assert "DATABASE_URL must not be SQLite" in message
    assert "FOR UPDATE" in message


def test_production_refuses_a_missing_database_url():
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            database_url="   ",
        )

    assert "DATABASE_URL must be set" in str(exc_info.value)


def test_a_redis_state_backend_does_not_excuse_a_sqlite_database_url():
    """The residual hole this guard exists to close.

    ``app/core/durable_state.py`` already refuses SQLite, but it governs the
    key/value *state store*. A deployment with ``STATE_BACKEND=redis`` and a
    ``REDIS_URL`` satisfies that check completely while ``DATABASE_URL`` stays
    SQLite -- and the wallet, permit, and ledger writes run against the ORM
    engine that URL builds, not against the state store. Passing the state
    check must not carry the ORM engine with it.
    """
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            redis_url="redis://redis.internal:6379/0",
            database_url="sqlite+aiosqlite:///./trust.db",
        )

    assert "DATABASE_URL must not be SQLite" in str(exc_info.value)


def test_production_accepts_a_postgres_database_url():
    validate_trust_mode_config(
        environment="production",
        trust_mode_enabled=True,
        signing_private_key_b64=VALID_SIGNING_PRIVATE_KEY_B64,
        allow_legacy_unpermitted_mcp=False,
        enable_proof_surfaces=False,
        database_url=VALID_PRODUCTION_DATABASE_URL,
    )


@pytest.mark.parametrize("environment", ["", "local", "development", "test", "ci"])
def test_local_environments_still_accept_sqlite(environment: str):
    """The guard must not make local development impossible.

    A SQLite ``DATABASE_URL`` is the standard local value and the default the
    test suite itself runs on; refusing it outside production-like
    environments would break every developer and this suite with them.
    """
    validate_trust_mode_config(
        environment=environment,
        trust_mode_enabled=True,
        signing_private_key_b64="",
        allow_legacy_unpermitted_mcp=True,
        database_url="sqlite+aiosqlite:///./test.db",
    )


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
    assert any("trust_mode_permissive" in record.getMessage() for record in records), (
        records
    )


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


@pytest.mark.anyio
async def test_lifespan_refuses_a_sqlite_database_url_in_production(monkeypatch):
    """The guard has to stop a real boot, not only pass a unit test.

    ``validate_trust_mode_guardrails`` is called from ``lifespan``, so a
    production deployment pointed at SQLite fails to start rather than serving
    traffic with the row locks silently absent. Asserting the function in
    isolation would not catch the guard being dropped from the startup path.
    """
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(main_module.settings, "TRUST_MODE_ENABLED", True)
    monkeypatch.setattr(
        main_module.settings,
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        VALID_SIGNING_PRIVATE_KEY_B64,
    )
    monkeypatch.setattr(main_module.settings, "ALLOW_LEGACY_UNPERMITTED_MCP", False)
    monkeypatch.setattr(main_module.settings, "ENABLE_PROOF_SURFACES", False)
    monkeypatch.setattr(main_module.settings, "DEBUG", False)
    monkeypatch.setattr(main_module.settings, "WEBAUTHN_ALLOW_MOCK", False)
    monkeypatch.setattr(
        main_module.settings, "DATABASE_URL", "sqlite+aiosqlite:///./trust.db"
    )

    with pytest.raises(TrustModeGuardrailError) as exc_info:
        async with main_module.lifespan(main_module.app):
            pytest.fail("lifespan must not start against SQLite in production")

    assert "DATABASE_URL must not be SQLite" in str(exc_info.value)
