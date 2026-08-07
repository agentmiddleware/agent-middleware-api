"""Post-deploy retirement coverage for retained owner-key columns."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, text

from scripts import retire_owner_keys


def _create_legacy_schema(
    sync_url: str,
    *,
    complete: bool = True,
    include_refresh_tokens: bool = True,
) -> None:
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE wallets (
                    wallet_id VARCHAR(50) PRIMARY KEY,
                    owner_key VARCHAR(255) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE service_registry (
                    service_id VARCHAR(100) PRIMARY KEY,
                    owner_key VARCHAR(255) NOT NULL
                )
                """
                if complete
                else """
                CREATE TABLE service_registry (
                    service_id VARCHAR(100) PRIMARY KEY
                )
                """
            )
        )
        if include_refresh_tokens:
            connection.execute(
                text(
                    """
                    CREATE TABLE refresh_tokens (
                        jti VARCHAR(64) PRIMARY KEY,
                        key_id VARCHAR(50),
                        revoked BOOLEAN NOT NULL
                    )
                    """
                )
            )
    engine.dispose()


def test_post_deploy_rescrub_closes_old_worker_write_race_and_is_idempotent(
    tmp_path,
):
    db_path = tmp_path / "owner-key-rescrub.db"
    sync_url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    secret = "b2a_live_old_worker_secret"
    _create_legacy_schema(sync_url)

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wallets (wallet_id, owner_key) VALUES ('wallet-race', '')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO service_registry (service_id, owner_key) "
                "VALUES ('service-race', '')"
            )
        )
        # Simulate the previous release writing after migration 025's first
        # scrub but before Railway has drained that worker.
        connection.execute(
            text("UPDATE wallets SET owner_key = :secret"),
            {"secret": secret},
        )
        connection.execute(
            text("UPDATE service_registry SET owner_key = :secret"),
            {"secret": secret},
        )
        # Simulate an old worker writing after migration 028 ran. Bound rows
        # from current workers and rows already revoked must remain unchanged.
        connection.execute(
            text(
                """
                INSERT INTO refresh_tokens (jti, key_id, revoked) VALUES
                    ('late-unbound', NULL, 0),
                    ('current-bound', 'key-current', 0),
                    ('already-revoked', NULL, 1)
                """
            )
        )
    engine.dispose()

    first = asyncio.run(retire_owner_keys.retire_owner_keys(async_url))
    second = asyncio.run(retire_owner_keys.retire_owner_keys(async_url))

    assert first == {
        "wallets": 1,
        "service_registry": 1,
        "unbound_refresh_tokens": 1,
    }
    assert second == {
        "wallets": 0,
        "service_registry": 0,
        "unbound_refresh_tokens": 0,
    }

    engine = create_engine(sync_url)
    with engine.connect() as connection:
        values = (
            connection.execute(
                text(
                    """
                SELECT owner_key FROM wallets
                UNION ALL
                SELECT owner_key FROM service_registry
                """
                )
            )
            .scalars()
            .all()
        )
        refresh_rows = connection.execute(
            text(
                """
                SELECT jti, key_id, revoked
                FROM refresh_tokens
                ORDER BY jti
                """
            )
        ).all()
    engine.dispose()
    assert values == ["", ""]
    assert secret not in repr(values)
    assert refresh_rows == [
        ("already-revoked", None, 1),
        ("current-bound", "key-current", 0),
        ("late-unbound", None, 1),
    ]


def test_rescrub_fails_before_writing_when_compatibility_schema_is_incomplete(
    tmp_path,
):
    db_path = tmp_path / "owner-key-incomplete.db"
    sync_url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    secret = "must-remain-for-rollback-proof"
    _create_legacy_schema(sync_url, complete=False)

    engine = create_engine(sync_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wallets (wallet_id, owner_key) "
                "VALUES ('wallet-incomplete', :secret)"
            ),
            {"secret": secret},
        )
    engine.dispose()

    with pytest.raises(
        retire_owner_keys.OwnerKeyRetirementError,
        match="retirement columns are missing",
    ):
        asyncio.run(retire_owner_keys.retire_owner_keys(async_url))

    engine = create_engine(sync_url)
    with engine.connect() as connection:
        retained = connection.execute(
            text("SELECT owner_key FROM wallets")
        ).scalar_one()
    engine.dispose()
    assert retained == secret


def test_rescrub_requires_refresh_token_binding_schema(tmp_path):
    db_path = tmp_path / "missing-refresh-token-schema.db"
    sync_url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    _create_legacy_schema(sync_url, include_refresh_tokens=False)

    with pytest.raises(
        retire_owner_keys.OwnerKeyRetirementError,
        match="retirement columns are missing",
    ):
        asyncio.run(retire_owner_keys.retire_owner_keys(async_url))


def test_command_requires_public_url_without_private_fallback(
    monkeypatch,
    capsys,
):
    private_url = "postgresql://user:private-secret@postgres.railway.internal/db"
    monkeypatch.setenv("DATABASE_URL", private_url)
    monkeypatch.delenv("DATABASE_PUBLIC_URL", raising=False)

    assert retire_owner_keys.main() == 1

    captured = capsys.readouterr()
    assert "DATABASE_PUBLIC_URL is required" in captured.err
    assert private_url not in captured.err
    assert "private-secret" not in captured.err


def test_command_failure_never_renders_public_database_url(
    monkeypatch,
    capsys,
):
    public_url = "postgresql://user:public-secret@switchback.proxy.rlwy.net:5432/db"
    monkeypatch.setenv("DATABASE_PUBLIC_URL", public_url)

    async def fail(_url):
        raise RuntimeError(f"failed against {public_url}")

    monkeypatch.setattr(retire_owner_keys, "retire_owner_keys", fail)

    assert retire_owner_keys.main() == 1
    captured = capsys.readouterr()
    assert "public database scrub or verification failed" in captured.err
    assert public_url not in captured.err
    assert "public-secret" not in captured.err
