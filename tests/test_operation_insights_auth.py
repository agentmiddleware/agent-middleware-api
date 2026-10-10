"""Synthetic reporting identity and authorization boundary tests."""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from app.core.auth import CREDENTIAL_ACCEPTANCE, CredentialAcceptance
from app.core.config import get_settings
from fastapi import HTTPException
from sqlalchemy import UniqueConstraint, event, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    async_sessionmaker,
    create_async_engine,
)


ISSUER = "https://example.okta.com/oauth2/default"
AUDIENCE = "api://agent-middleware-insights"
CLIENT_ID = "synthetic-oidc-client-id"


def _b64_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def trusted_issuer(monkeypatch: pytest.MonkeyPatch, signing_key):
    numbers = signing_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "insight-test-key",
                "n": _b64_uint(numbers.n),
                "e": _b64_uint(numbers.e),
            }
        ]
    }
    monkeypatch.setenv(
        "IGA_TRUSTED_ISSUERS",
        json.dumps(
            {
                ISSUER: {
                    "audience": AUDIENCE,
                    "algorithms": ["RS256"],
                    "jwks": jwks,
                }
            }
        ),
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mint(signing_key, **claims: object) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "sub": "operator-1",
        "aud": AUDIENCE,
        "iat": now - timedelta(minutes=1),
        "exp": now + timedelta(minutes=5),
    }
    payload.update(claims)
    private_pem = signing_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    return jwt.encode(
        payload, private_pem, algorithm="RS256", headers={"kid": "insight-test-key"}
    )


def test_verified_bearer_accepts_exact_enterprise_identity(
    trusted_issuer, signing_key
) -> None:
    from app.services.operation_insights.auth import get_reporting_principal

    holder = CredentialAcceptance()
    marker = CREDENTIAL_ACCEPTANCE.set(holder)
    try:
        principal = get_reporting_principal(
            authorization=f"Bearer {_mint(signing_key, email='same@example.com', groups=['admins'])}",
            x_api_key=None,
        )
    finally:
        CREDENTIAL_ACCEPTANCE.reset(marker)

    assert (principal.issuer, principal.subject) == (ISSUER, "operator-1")
    assert holder.accepted is True


@pytest.mark.parametrize(
    ("credential_kind", "expected_status"),
    [
        ("missing", 401),
        ("malformed", 401),
        ("api_key", 401),
        ("dual", 401),
        ("bad_signature", 401),
        ("wrong_issuer", 401),
        ("wrong_audience", 401),
        ("id_token_client_audience", 401),
        ("expired", 401),
        ("no_subject", 401),
        ("internal_wallet_jwt", 401),
    ],
)
def test_invalid_or_mixed_credentials_remain_unaccepted(
    trusted_issuer, signing_key, credential_kind: str, expected_status: int
) -> None:
    from app.services.operation_insights.auth import get_reporting_principal

    token = _mint(signing_key)
    authorization = f"Bearer {token}"
    api_key = None
    if credential_kind == "missing":
        authorization = None
    elif credential_kind == "malformed":
        authorization = f"Basic {token}"
    elif credential_kind == "api_key":
        authorization = None
        api_key = "synthetic-wallet-key"  # pragma: allowlist secret
    elif credential_kind == "dual":
        api_key = "synthetic-wallet-key"  # pragma: allowlist secret
    elif credential_kind == "bad_signature":
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        authorization = f"Bearer {_mint(wrong_key)}"
    elif credential_kind == "wrong_issuer":
        authorization = f"Bearer {_mint(signing_key, iss='https://evil.example.com')}"
    elif credential_kind in {"wrong_audience", "id_token_client_audience"}:
        authorization = f"Bearer {_mint(signing_key, aud=CLIENT_ID)}"
    elif credential_kind == "expired":
        authorization = f"Bearer {_mint(signing_key, exp=datetime.now(timezone.utc) - timedelta(seconds=1))}"
    elif credential_kind == "no_subject":
        authorization = f"Bearer {_mint(signing_key, sub=None)}"
    elif credential_kind == "internal_wallet_jwt":
        authorization = f"Bearer {_mint(signing_key, iss='amw-internal')}"

    holder = CredentialAcceptance()
    marker = CREDENTIAL_ACCEPTANCE.set(holder)
    try:
        with pytest.raises(HTTPException) as exc:
            get_reporting_principal(authorization=authorization, x_api_key=api_key)
    finally:
        CREDENTIAL_ACCEPTANCE.reset(marker)
    assert exc.value.status_code == expected_status
    assert exc.value.detail == "insight_authentication_required"
    assert holder.accepted is False


def test_unconfigured_issuer_remains_unaccepted(
    monkeypatch: pytest.MonkeyPatch, signing_key
) -> None:
    from app.services.operation_insights.auth import get_reporting_principal

    monkeypatch.setenv("IGA_TRUSTED_ISSUERS", "")
    get_settings.cache_clear()
    holder = CredentialAcceptance()
    marker = CREDENTIAL_ACCEPTANCE.set(holder)
    try:
        with pytest.raises(HTTPException) as exc:
            get_reporting_principal(
                authorization=f"Bearer {_mint(signing_key)}", x_api_key=None
            )
    finally:
        CREDENTIAL_ACCEPTANCE.reset(marker)
        get_settings.cache_clear()
    assert exc.value.status_code == 401
    assert holder.accepted is False


def test_bad_bearer_never_appears_in_logs(
    trusted_issuer, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services.operation_insights.auth import get_reporting_principal

    presented_token = "synthetic.invalid.private-token-material"
    with pytest.raises(HTTPException) as exc:
        get_reporting_principal(
            authorization=f"Bearer {presented_token}", x_api_key=None
        )
    assert exc.value.status_code == 401
    assert presented_token not in caplog.text


def test_reporting_authority_has_separate_principal_epoch_and_grant_models() -> None:
    from app.db.models import (
        InsightReportingPrincipal,
        InsightReportingWalletGrant,
        InsightWalletOwnershipEpoch,
    )

    assert InsightReportingPrincipal.__tablename__ == "insight_reporting_principals"
    assert (
        InsightWalletOwnershipEpoch.__tablename__ == "insight_wallet_ownership_epochs"
    )
    assert (
        InsightReportingWalletGrant.__tablename__ == "insight_reporting_wallet_grants"
    )
    principal_uniques = {
        tuple(item.columns.keys())
        for item in InsightReportingPrincipal.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }
    grant_uniques = {
        tuple(item.columns.keys())
        for item in InsightReportingWalletGrant.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }
    assert ("issuer", "subject") in principal_uniques
    assert ("principal_id", "wallet_id", "ownership_epoch_id") in grant_uniques


def test_reporting_authority_migration_is_local_revision_after_042() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script.get_revision("amw_insights_authority_20261010")

    assert revision.down_revision == "042_permit_action_binding"
    assert revision.path.endswith("044_amw_insights_authority.py")


# These cases run against only the dedicated synthetic PostgreSQL database.
# The ordinary SQLite suite records explicit skips rather than hidden coverage.
_PG_TEST_URL = os.environ.get("AMW_INSIGHTS_TEST_DATABASE_URL")
_DISPOSABLE_PG_TEST_URL = (
    "postgresql+asyncpg://sellers@127.0.0.1:55489/amw_insights_auth_test"
)


def _require_disposable_pg_url(url: str | None) -> str:
    if url != _DISPOSABLE_PG_TEST_URL:
        raise RuntimeError(
            "only the designated disposable loopback database is allowed"
        )
    return url


async def _assert_synthetic_authority_rows(connection: AsyncConnection) -> None:
    checks = (
        (
            "insight_reporting_principals",
            "principal_id !~ '^principal-[0-9a-f]{12}$' "
            "OR issuer != :issuer OR subject !~ '^operator-[0-9a-f]{12}$'",
        ),
        (
            "insight_wallet_ownership_epochs",
            "ownership_epoch_id !~ '^(epoch-([0-9a-f]{12}|insight-[0-9a-f]{12})|other-[0-9a-f]{12})$' "
            "OR wallet_id !~ '^insight-[0-9a-f]{12}$' "
            "OR owner_boundary_id NOT IN ('synthetic-owner-A', 'synthetic-owner-B')",
        ),
        (
            "insight_reporting_wallet_grants",
            "grant_id !~ '^grant-([0-9a-f]{12}|insight-[0-9a-f]{12})$' "
            "OR principal_id !~ '^principal-[0-9a-f]{12}$' "
            "OR wallet_id !~ '^insight-[0-9a-f]{12}$' "
            "OR ownership_epoch_id !~ '^(epoch-([0-9a-f]{12}|insight-[0-9a-f]{12})|other-[0-9a-f]{12})$'",
        ),
    )
    for table, disallowed in checks:
        result = await connection.scalar(
            text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {disallowed})"),
            {"issuer": ISSUER},
        )
        if result:
            raise RuntimeError(
                "disposable authority database contains non-fixture rows"
            )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://sellers@db.example.com:55489/amw_insights_auth_test",
        "postgresql+asyncpg://sellers@127.0.0.1:5432/amw_insights_auth_test",
        "postgresql+asyncpg://sellers@127.0.0.1:55489/production",
        "postgresql+asyncpg://sellers:password@127.0.0.1:55489/amw_insights_auth_test",  # pragma: allowlist secret
    ],
)
def test_pg_fixture_rejects_unsafe_database_urls(url: str) -> None:
    with pytest.raises(RuntimeError, match="disposable"):
        _require_disposable_pg_url(url)


def test_pg_fixture_accepts_only_designated_loopback_url() -> None:
    assert _require_disposable_pg_url(_DISPOSABLE_PG_TEST_URL) == (
        _DISPOSABLE_PG_TEST_URL
    )


@pytest_asyncio.fixture
async def pg_factory():
    url = _require_disposable_pg_url(_PG_TEST_URL)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            await _assert_synthetic_authority_rows(connection)
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_pg_fixture_rejects_non_fixture_authority_rows(pg_factory) -> None:
    engine = pg_factory.kw["bind"]
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    "INSERT INTO insight_reporting_principals "
                    "(principal_id, issuer, subject, starts_at, expires_at, allow_unknown_wallet_counts) "
                    "VALUES ('external-principal', :issuer, 'external-subject', :starts, :expires, false)"
                ),
                {
                    "issuer": ISSUER,
                    "starts": datetime(2026, 1, 1),
                    "expires": datetime(2027, 1, 1),
                },
            )
            with pytest.raises(RuntimeError, match="non-fixture rows"):
                await _assert_synthetic_authority_rows(connection)
        finally:
            await transaction.rollback()


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_authority_model_columns_match_applied_migration(pg_factory) -> None:
    from app.db.models import (
        InsightReportingPrincipal,
        InsightReportingWalletGrant,
        InsightWalletOwnershipEpoch,
    )

    models = (
        InsightReportingPrincipal,
        InsightWalletOwnershipEpoch,
        InsightReportingWalletGrant,
    )
    engine = pg_factory.kw["bind"]
    async with engine.connect() as connection:
        for model in models:
            actual = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns(
                    model.__tablename__
                )
            )
            assert {column["name"]: column["nullable"] for column in actual} == {
                column.name: column.nullable for column in model.__table__.columns
            }


async def _seed_authority(
    factory,
    *,
    allow_unknown: bool = False,
    subject: str | None = None,
    epoch_until: datetime = datetime(2027, 1, 1),
    grant_until: datetime = datetime(2026, 12, 1),
) -> tuple[str, str, str, object]:
    from app.core.oidc_iga import EnterprisePrincipal
    from app.db.models import (
        InsightReportingPrincipal,
        InsightReportingWalletGrant,
        InsightWalletOwnershipEpoch,
        WalletModel,
    )

    suffix = uuid.uuid4().hex[:12]
    wallet_id = f"insight-{suffix}"
    principal_id = f"principal-{suffix}"
    epoch_id = f"epoch-{suffix}"
    subject = subject or f"operator-{suffix}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with factory() as session:
        session.add(
            WalletModel(
                wallet_id=wallet_id,
                wallet_type="agent",
                balance=Decimal("0"),
            )
        )
        await session.flush()
        session.add(
            InsightReportingPrincipal(
                principal_id=principal_id,
                issuer=ISSUER,
                subject=subject,
                starts_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=1),
                allow_unknown_wallet_counts=allow_unknown,
            )
        )
        await session.flush()
        session.add(
            InsightWalletOwnershipEpoch(
                ownership_epoch_id=epoch_id,
                wallet_id=wallet_id,
                owner_boundary_id="synthetic-owner-A",
                evidence_from=datetime(2026, 1, 1),
                evidence_until=epoch_until,
                history_complete=True,
            )
        )
        await session.flush()
        session.add(
            InsightReportingWalletGrant(
                grant_id=f"grant-{suffix}",
                principal_id=principal_id,
                wallet_id=wallet_id,
                ownership_epoch_id=epoch_id,
                starts_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=1),
                evidence_from=datetime(2026, 2, 1),
                evidence_until=grant_until,
            )
        )
        await session.commit()
    principal = EnterprisePrincipal(
        subject=subject, provider="okta", issuer=ISSUER, email="same@example.com"
    )
    return wallet_id, principal_id, epoch_id, principal


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_scope_contains_only_explicit_live_wallet_epoch(pg_factory) -> None:
    from app.services.operation_insights.auth import (
        assert_scope_bound,
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, epoch_id, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope = await authorize_scope(
                principal, frozenset({wallet_id}), False, session
            )
            assert scope.wallet_ids == frozenset({wallet_id})
            assert scope.allow_unknown_wallet_counts is False
            assert len(scope.authorized_ownership_epochs) == 1
            epoch = scope.authorized_ownership_epochs[0]
            assert (epoch.wallet_id, epoch.ownership_epoch_id) == (
                wallet_id,
                epoch_id,
            )
            assert epoch.evidence_from == datetime(2026, 2, 1, tzinfo=timezone.utc)
            assert epoch.evidence_until == datetime(2026, 12, 1, tzinfo=timezone.utc)
            assert assert_scope_bound(scope, session) is None
            assert (
                await session.scalar(text("SHOW transaction_isolation"))
            ) == "repeatable read"
            assert (await session.scalar(text("SHOW transaction_read_only"))) == "on"


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_missing_foreign_and_wildcard_wallets_deny(pg_factory) -> None:
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, _, principal = await _seed_authority(pg_factory)
    for requested in (frozenset(), frozenset({"*"}), frozenset({"foreign"})):
        async with pg_factory() as session:
            async with reporting_read_transaction(session):
                with pytest.raises(HTTPException) as exc:
                    await authorize_scope(principal, requested, False, session)
                assert exc.value.status_code == 403
    assert wallet_id != "foreign"


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_scope_binding_rejects_copy_forgery_session_and_ended_tx(
    pg_factory,
) -> None:
    from app.services.operation_insights.auth import (
        assert_scope_bound,
        authorize_scope,
        reporting_read_transaction,
    )
    from app.services.operation_insights.contracts import Scope

    wallet_id, _, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope = await authorize_scope(
                principal, frozenset({wallet_id}), False, session
            )
            for forged in (
                replace(scope),
                Scope(wallet_ids=frozenset({wallet_id})),
            ):
                with pytest.raises(HTTPException) as exc:
                    assert_scope_bound(forged, session)
                assert exc.value.status_code == 403
            async with pg_factory() as another_session:
                with pytest.raises(HTTPException) as exc:
                    assert_scope_bound(scope, another_session)
                assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            assert_scope_bound(scope, session)
        assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
@pytest.mark.parametrize("alteration", ["wallet", "epoch", "unknown"])
async def test_scope_binding_rejects_in_place_mutation(
    pg_factory, alteration: str
) -> None:
    from app.services.operation_insights.auth import (
        assert_scope_bound,
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope = await authorize_scope(
                principal, frozenset({wallet_id}), False, session
            )
            if alteration == "wallet":
                object.__setattr__(
                    scope, "wallet_ids", frozenset({wallet_id, "foreign"})
                )
            elif alteration == "epoch":
                object.__setattr__(
                    scope.authorized_ownership_epochs[0], "wallet_id", "foreign"
                )
            else:
                object.__setattr__(scope, "allow_unknown_wallet_counts", True)
            with pytest.raises(HTTPException) as exc:
                assert_scope_bound(scope, session)
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_unknown_wallet_count_bit_is_independent(pg_factory) -> None:
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(principal, frozenset({wallet_id}), True, session)
            assert exc.value.status_code == 403
    allowed_wallet, _, _, allowed_principal = await _seed_authority(
        pg_factory, allow_unknown=True
    )
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope = await authorize_scope(
                allowed_principal, frozenset({allowed_wallet}), True, session
            )
            assert scope.allow_unknown_wallet_counts is True


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_same_email_cannot_replace_exact_issuer_subject(pg_factory) -> None:
    from app.core.oidc_iga import EnterprisePrincipal
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, _, _ = await _seed_authority(pg_factory)
    another = EnterprisePrincipal(
        subject="different-subject",
        issuer=ISSUER,
        provider="okta",
        email="same@example.com",
        groups=("admins",),
    )
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(another, frozenset({wallet_id}), False, session)
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_revocation_is_visible_on_next_snapshot_only(pg_factory) -> None:
    from app.db.models import InsightReportingWalletGrant
    from app.services.operation_insights.auth import (
        assert_scope_bound,
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, principal_id, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as reading_session:
        async with reporting_read_transaction(reading_session):
            scope = await authorize_scope(
                principal, frozenset({wallet_id}), False, reading_session
            )
            async with pg_factory() as writing_session:
                grant = await writing_session.scalar(
                    select(InsightReportingWalletGrant).where(
                        InsightReportingWalletGrant.principal_id == principal_id
                    )
                )
                assert grant is not None
                grant.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await writing_session.commit()
            assert_scope_bound(scope, reading_session)
            unchanged = await reading_session.scalar(
                select(InsightReportingWalletGrant.revoked_at).where(
                    InsightReportingWalletGrant.principal_id == principal_id
                )
            )
            assert unchanged is None
    async with pg_factory() as next_session:
        async with reporting_read_transaction(next_session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(
                    principal, frozenset({wallet_id}), False, next_session
                )
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row_kind", "state"),
    [
        ("principal", "not_started"),
        ("principal", "expired"),
        ("principal", "revoked"),
        ("grant", "not_started"),
        ("grant", "expired"),
        ("grant", "revoked"),
    ],
)
async def test_inactive_principal_or_grant_denies_at_boundary(
    pg_factory, monkeypatch: pytest.MonkeyPatch, row_kind: str, state: str
) -> None:
    from app.db.models import InsightReportingPrincipal, InsightReportingWalletGrant
    from app.services.operation_insights import auth

    wallet_id, principal_id, _, principal = await _seed_authority(pg_factory)
    fixed_now = datetime(2026, 10, 10, 12)
    monkeypatch.setattr(auth, "utc_now", lambda: fixed_now)
    async with pg_factory() as session:
        if row_kind == "principal":
            row = await session.get(InsightReportingPrincipal, principal_id)
        else:
            row = await session.scalar(
                select(InsightReportingWalletGrant).where(
                    InsightReportingWalletGrant.principal_id == principal_id
                )
            )
        assert row is not None
        if state == "not_started":
            row.starts_at = fixed_now + timedelta(seconds=1)
            row.expires_at = fixed_now + timedelta(hours=1)
        elif state == "expired":
            row.starts_at = fixed_now - timedelta(hours=1)
            row.expires_at = fixed_now
        else:
            row.revoked_at = fixed_now
        await session.commit()
    async with pg_factory() as session:
        async with auth.reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await auth.authorize_scope(
                    principal, frozenset({wallet_id}), False, session
                )
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_principal_and_grant_start_are_inclusive(pg_factory, monkeypatch) -> None:
    from app.db.models import InsightReportingPrincipal, InsightReportingWalletGrant
    from app.services.operation_insights import auth

    wallet_id, principal_id, _, principal = await _seed_authority(pg_factory)
    fixed_now = datetime(2026, 10, 10, 12)
    monkeypatch.setattr(auth, "utc_now", lambda: fixed_now)
    async with pg_factory() as session:
        stored_principal = await session.get(InsightReportingPrincipal, principal_id)
        stored_grant = await session.scalar(
            select(InsightReportingWalletGrant).where(
                InsightReportingWalletGrant.principal_id == principal_id
            )
        )
        assert stored_principal is not None
        assert stored_grant is not None
        stored_principal.starts_at = fixed_now
        stored_grant.starts_at = fixed_now
        await session.commit()
    async with pg_factory() as session:
        async with auth.reporting_read_transaction(session):
            scope = await auth.authorize_scope(
                principal, frozenset({wallet_id}), False, session
            )
            assert scope.wallet_ids == frozenset({wallet_id})


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
@pytest.mark.parametrize("history_state", ["incomplete", "overlap", "gap"])
async def test_incomplete_or_conflicting_wallet_history_denies(
    pg_factory, history_state: str
) -> None:
    from app.db.models import InsightWalletOwnershipEpoch
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, epoch_id, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        if history_state == "incomplete":
            epoch = await session.get(InsightWalletOwnershipEpoch, epoch_id)
            assert epoch is not None
            epoch.history_complete = False
        else:
            session.add(
                InsightWalletOwnershipEpoch(
                    ownership_epoch_id=f"other-{uuid.uuid4().hex[:12]}",
                    wallet_id=wallet_id,
                    owner_boundary_id="synthetic-owner-B",
                    evidence_from=(
                        datetime(2026, 12, 31)
                        if history_state == "overlap"
                        else datetime(2027, 1, 2)
                    ),
                    evidence_until=datetime(2028, 1, 1),
                    history_complete=True,
                )
            )
        await session.commit()
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(principal, frozenset({wallet_id}), False, session)
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_grant_cannot_extend_epoch_evidence_interval(pg_factory) -> None:
    from app.db.models import InsightReportingWalletGrant
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, principal_id, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        grant = await session.scalar(
            select(InsightReportingWalletGrant).where(
                InsightReportingWalletGrant.principal_id == principal_id
            )
        )
        assert grant is not None
        grant.evidence_from = datetime(2025, 12, 31)
        await session.commit()
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(principal, frozenset({wallet_id}), False, session)
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_unknown_grant_permission_kind_denies(pg_factory) -> None:
    from app.db.models import InsightReportingWalletGrant
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, principal_id, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        grant = await session.scalar(
            select(InsightReportingWalletGrant).where(
                InsightReportingWalletGrant.principal_id == principal_id
            )
        )
        assert grant is not None
        grant.permission_kind = "wallet_admin"
        await session.commit()
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(principal, frozenset({wallet_id}), False, session)
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_grant_storage_error_denies_without_scope(
    pg_factory, monkeypatch
) -> None:
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, _, principal = await _seed_authority(pg_factory)
    async with pg_factory() as session:
        async with reporting_read_transaction(session):

            async def fail_storage(*_args, **_kwargs):
                raise OperationalError("synthetic store unavailable", {}, None)

            monkeypatch.setattr(session, "execute", fail_storage)
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(principal, frozenset({wallet_id}), False, session)
            assert exc.value.status_code == 503
            assert exc.value.detail == "insight_authority_unavailable"


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_reporting_transaction_rejects_business_write(pg_factory) -> None:
    from app.services.operation_insights.auth import reporting_read_transaction

    async with pg_factory() as session:
        with pytest.raises(DBAPIError) as exc:
            async with reporting_read_transaction(session):
                await session.execute(
                    text("UPDATE insight_reporting_principals SET subject = subject")
                )
        assert exc.value.orig.sqlstate == "25006"


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_database_constraints_reject_duplicate_grant_and_wrong_epoch_wallet(
    pg_factory,
) -> None:
    from app.db.models import InsightReportingWalletGrant, WalletModel

    wallet_id, principal_id, epoch_id, _ = await _seed_authority(pg_factory)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with pg_factory() as session:
        session.add(
            InsightReportingWalletGrant(
                grant_id=f"duplicate-{uuid.uuid4().hex[:10]}",
                principal_id=principal_id,
                wallet_id=wallet_id,
                ownership_epoch_id=epoch_id,
                starts_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=1),
                evidence_from=datetime(2026, 2, 1),
                evidence_until=datetime(2026, 12, 1),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        wrong_wallet = f"wrong-{uuid.uuid4().hex[:10]}"
        session.add(WalletModel(wallet_id=wrong_wallet, wallet_type="agent"))
        await session.flush()
        session.add(
            InsightReportingWalletGrant(
                grant_id=f"mismatch-{uuid.uuid4().hex[:10]}",
                principal_id=principal_id,
                wallet_id=wrong_wallet,
                ownership_epoch_id=epoch_id,
                starts_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=1),
                evidence_from=datetime(2026, 2, 1),
                evidence_until=datetime(2026, 12, 1),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_two_explicit_wallet_grants_do_not_inherit_an_expired_third(
    pg_factory,
) -> None:
    from app.db.models import (
        InsightReportingWalletGrant,
        InsightWalletOwnershipEpoch,
        WalletModel,
    )
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    first_wallet, principal_id, _, principal = await _seed_authority(pg_factory)
    suffix = uuid.uuid4().hex[:12]
    second_wallet = f"insight-{suffix}"
    third_wallet = f"insight-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with pg_factory() as session:
        for wallet in (second_wallet, third_wallet):
            session.add(WalletModel(wallet_id=wallet, wallet_type="agent"))
        await session.flush()
        for wallet, expired in ((second_wallet, False), (third_wallet, True)):
            epoch_id = f"epoch-{wallet}"
            session.add(
                InsightWalletOwnershipEpoch(
                    ownership_epoch_id=epoch_id,
                    wallet_id=wallet,
                    owner_boundary_id="synthetic-owner-A",
                    evidence_from=datetime(2026, 1, 1),
                    evidence_until=datetime(2027, 1, 1),
                    history_complete=True,
                )
            )
            await session.flush()
            session.add(
                InsightReportingWalletGrant(
                    grant_id=f"grant-{wallet}",
                    principal_id=principal_id,
                    wallet_id=wallet,
                    ownership_epoch_id=epoch_id,
                    starts_at=now - timedelta(days=2),
                    expires_at=(
                        now - timedelta(days=1) if expired else now + timedelta(days=1)
                    ),
                    evidence_from=datetime(2026, 2, 1),
                    evidence_until=datetime(2026, 12, 1),
                )
            )
        await session.commit()
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope = await authorize_scope(
                principal, frozenset({first_wallet, second_wallet}), False, session
            )
            assert scope.wallet_ids == frozenset({first_wallet, second_wallet})
            assert len(scope.authorized_ownership_epochs) == 2
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            with pytest.raises(HTTPException) as exc:
                await authorize_scope(
                    principal, frozenset({first_wallet, third_wallet}), False, session
                )
            assert exc.value.status_code == 403


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_transfer_grants_stay_in_separate_half_open_epochs(pg_factory) -> None:
    from app.core.oidc_iga import EnterprisePrincipal
    from app.db.models import (
        InsightReportingPrincipal,
        InsightReportingWalletGrant,
        InsightWalletOwnershipEpoch,
    )
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    boundary = datetime(2026, 7, 1)
    wallet_id, _, epoch_a_id, principal_a = await _seed_authority(
        pg_factory, epoch_until=boundary, grant_until=boundary
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    suffix = uuid.uuid4().hex[:12]
    principal_b_id = f"principal-{suffix}"
    subject_b = f"operator-{suffix}"
    epoch_b_id = f"epoch-{suffix}"
    async with pg_factory() as session:
        session.add(
            InsightReportingPrincipal(
                principal_id=principal_b_id,
                issuer=ISSUER,
                subject=subject_b,
                starts_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=1),
            )
        )
        session.add(
            InsightWalletOwnershipEpoch(
                ownership_epoch_id=epoch_b_id,
                wallet_id=wallet_id,
                owner_boundary_id="synthetic-owner-B",
                evidence_from=boundary,
                evidence_until=datetime(2027, 1, 1),
                history_complete=True,
            )
        )
        await session.flush()
        session.add(
            InsightReportingWalletGrant(
                grant_id=f"grant-{suffix}",
                principal_id=principal_b_id,
                wallet_id=wallet_id,
                ownership_epoch_id=epoch_b_id,
                starts_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=1),
                evidence_from=boundary,
                evidence_until=datetime(2026, 12, 1),
            )
        )
        await session.commit()
    principal_b = EnterprisePrincipal(subject=subject_b, provider="okta", issuer=ISSUER)
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope_a = await authorize_scope(
                principal_a, frozenset({wallet_id}), False, session
            )
            assert scope_a.authorized_ownership_epochs[0].ownership_epoch_id == (
                epoch_a_id
            )
            assert scope_a.authorized_ownership_epochs[0].evidence_until == (
                boundary.replace(tzinfo=timezone.utc)
            )
    async with pg_factory() as session:
        async with reporting_read_transaction(session):
            scope_b = await authorize_scope(
                principal_b, frozenset({wallet_id}), False, session
            )
            assert scope_b.authorized_ownership_epochs[0].ownership_epoch_id == (
                epoch_b_id
            )
            assert scope_b.authorized_ownership_epochs[0].evidence_from == (
                boundary.replace(tzinfo=timezone.utc)
            )


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_successful_scope_read_never_accesses_api_keys_or_writes(
    pg_factory,
) -> None:
    from app.services.operation_insights.auth import (
        authorize_scope,
        reporting_read_transaction,
    )

    wallet_id, _, _, principal = await _seed_authority(pg_factory)
    engine = pg_factory.kw["bind"]
    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture_sql)
    try:
        async with pg_factory() as session:
            async with reporting_read_transaction(session):
                scope = await authorize_scope(
                    principal, frozenset({wallet_id}), False, session
                )
                assert scope.wallet_ids == frozenset({wallet_id})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_sql)
    assert len(statements) == 5
    assert all(
        statement.lstrip().startswith(("select", "set transaction"))
        for statement in statements
    )
    assert all("api_keys" not in statement for statement in statements)


@pytest.mark.skipif(
    not _PG_TEST_URL,
    reason="owner: reporting auth; isolated PostgreSQL test database required; see docs/amw-insights-auth-amendment.md",
)
@pytest.mark.asyncio
async def test_valid_bearer_with_denied_wallet_is_authenticated(
    pg_factory, trusted_issuer, signing_key
) -> None:
    from app.services.operation_insights.auth import (
        authorize_scope,
        get_reporting_principal,
        reporting_read_transaction,
    )

    wallet_id, _, _, _ = await _seed_authority(pg_factory)
    holder = CredentialAcceptance()
    marker = CREDENTIAL_ACCEPTANCE.set(holder)
    try:
        principal = get_reporting_principal(
            authorization=f"Bearer {_mint(signing_key)}", x_api_key=None
        )
        async with pg_factory() as session:
            async with reporting_read_transaction(session):
                with pytest.raises(HTTPException) as exc:
                    await authorize_scope(
                        principal, frozenset({wallet_id}), False, session
                    )
                assert exc.value.status_code == 403
        assert holder.accepted is True
    finally:
        CREDENTIAL_ACCEPTANCE.reset(marker)
