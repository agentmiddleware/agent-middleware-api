"""Read-only reporting identity and transaction-scoped authorization."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator, NoReturn

from fastapi import Header, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.auth import CREDENTIAL_ACCEPTANCE
from app.core.oidc_iga import EnterprisePrincipal, IGAError, parse_enterprise_token
from app.core.time import utc_now
from app.db.models import (
    InsightReportingPrincipal,
    InsightReportingWalletGrant,
    InsightWalletOwnershipEpoch,
    WalletModel,
)
from app.services.operation_insights.contracts import AuthorizedOwnershipEpoch, Scope


_BEARER = re.compile(r"\A(?i:Bearer) ([A-Za-z0-9._~-]+)\Z")
_WALLET_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,49}\Z")
_TRANSACTION_KEY = object()
_SCOPE_KEY = object()


def _deny() -> NoReturn:
    raise HTTPException(status_code=403, detail="insight_scope_denied")


def _unavailable() -> NoReturn:
    raise HTTPException(status_code=503, detail="insight_authority_unavailable")


def get_reporting_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> EnterprisePrincipal:
    """Accept only a fully verified enterprise access-token identity."""
    if x_api_key is not None or authorization is None:
        raise HTTPException(status_code=401, detail="insight_authentication_required")
    match = _BEARER.fullmatch(authorization)
    if match is None:
        raise HTTPException(status_code=401, detail="insight_authentication_required")
    try:
        principal = parse_enterprise_token(match.group(1))
    except IGAError as exc:
        raise HTTPException(
            status_code=401, detail="insight_authentication_required"
        ) from exc
    acceptance = CREDENTIAL_ACCEPTANCE.get()
    if acceptance is not None:
        acceptance.accepted = True
    return principal


@asynccontextmanager
async def reporting_read_transaction(
    session: AsyncSession,
) -> AsyncIterator[AsyncSession]:
    """Own one PostgreSQL repeatable-read, read-only request transaction."""
    try:
        dialect = session.get_bind().dialect.name
    except SQLAlchemyError:
        _unavailable()
    if dialect != "postgresql" or session.in_transaction():
        _unavailable()
    async with session.begin():
        try:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
        except SQLAlchemyError:
            _unavailable()
        transaction = session.sync_session.get_transaction()
        if transaction is None:
            _unavailable()
        session.info[_TRANSACTION_KEY] = transaction
        try:
            yield session
        finally:
            session.info.pop(_SCOPE_KEY, None)
            session.info.pop(_TRANSACTION_KEY, None)


def _active_transaction(session: AsyncSession) -> bool:
    transaction = session.sync_session.get_transaction()
    if transaction is None:
        return False
    return (
        transaction is session.info.get(_TRANSACTION_KEY)
        and bool(getattr(transaction, "is_active", False))
        and session.in_transaction()
    )


def _scope_fingerprint(
    scope: Scope,
) -> tuple[tuple[str, ...], tuple[tuple[str, str, datetime, datetime], ...], bool]:
    if (
        type(scope.wallet_ids) is not frozenset
        or type(scope.authorized_ownership_epochs) is not tuple
        or type(scope.allow_unknown_wallet_counts) is not bool
        or any(type(wallet_id) is not str for wallet_id in scope.wallet_ids)
    ):
        _deny()
    epochs: list[tuple[str, str, datetime, datetime]] = []
    for epoch in scope.authorized_ownership_epochs:
        if (
            type(epoch) is not AuthorizedOwnershipEpoch
            or type(epoch.wallet_id) is not str
            or type(epoch.ownership_epoch_id) is not str
            or type(epoch.evidence_from) is not datetime
            or type(epoch.evidence_until) is not datetime
        ):
            _deny()
        epochs.append(
            (
                epoch.wallet_id,
                epoch.ownership_epoch_id,
                epoch.evidence_from,
                epoch.evidence_until,
            )
        )
    return (
        tuple(sorted(scope.wallet_ids)),
        tuple(epochs),
        scope.allow_unknown_wallet_counts,
    )


def assert_scope_bound(scope: Scope, session: AsyncSession) -> None:
    """Reject scopes not minted in this exact still-active transaction."""
    if not _active_transaction(session):
        _deny()
    bound = session.info.get(_SCOPE_KEY)
    if bound is None or bound[0] is not scope or bound[1] != _scope_fingerprint(scope):
        _deny()


def _valid_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _valid_interval(start: object, end: object) -> bool:
    return (
        isinstance(start, datetime)
        and isinstance(end, datetime)
        and start.tzinfo is None
        and end.tzinfo is None
        and start < end
    )


def _live(start: object, end: object, revoked: object, now: datetime) -> bool:
    if not _valid_interval(start, end) or revoked is not None:
        return False
    assert isinstance(start, datetime) and isinstance(end, datetime)
    return start <= now < end


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc)


async def authorize_scope(
    principal: EnterprisePrincipal,
    requested_wallets: frozenset[str],
    include_unknown: bool,
    session: AsyncSession,
) -> Scope:
    """Resolve live exact grants and complete immutable ownership history."""
    session.info.pop(_SCOPE_KEY, None)
    if not _active_transaction(session):
        _deny()
    if (
        not isinstance(principal, EnterprisePrincipal)
        or not _valid_identity(principal.issuer)
        or not _valid_identity(principal.subject)
        or not isinstance(requested_wallets, frozenset)
        or not requested_wallets
        or any(
            not isinstance(wallet_id, str) or not _WALLET_ID.fullmatch(wallet_id)
            for wallet_id in requested_wallets
        )
        or type(include_unknown) is not bool
    ):
        _deny()

    now = utc_now()  # One UTC evaluation time for principal and every grant.
    try:
        principals = (
            (
                await session.execute(
                    select(InsightReportingPrincipal).where(
                        col(InsightReportingPrincipal.issuer) == principal.issuer,
                        col(InsightReportingPrincipal.subject) == principal.subject,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(principals) != 1:
            _deny()
        authority = principals[0]
        if (
            not _valid_identity(authority.principal_id)
            or not _valid_identity(authority.issuer)
            or not _valid_identity(authority.subject)
            or type(authority.allow_unknown_wallet_counts) is not bool
            or not _valid_interval(authority.starts_at, authority.expires_at)
            or (
                authority.revoked_at is not None
                and (
                    not isinstance(authority.revoked_at, datetime)
                    or authority.revoked_at.tzinfo is not None
                )
            )
            or not _live(
                authority.starts_at, authority.expires_at, authority.revoked_at, now
            )
            or (include_unknown and not authority.allow_unknown_wallet_counts)
        ):
            _deny()

        wallets = set(
            (
                await session.execute(
                    select(col(WalletModel.wallet_id)).where(
                        col(WalletModel.wallet_id).in_(requested_wallets)
                    )
                )
            )
            .scalars()
            .all()
        )
        if wallets != requested_wallets:
            _deny()

        grants = (
            (
                await session.execute(
                    select(InsightReportingWalletGrant).where(
                        col(InsightReportingWalletGrant.principal_id)
                        == authority.principal_id,
                        col(InsightReportingWalletGrant.wallet_id).in_(
                            requested_wallets
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        seen_grants: set[tuple[str, str]] = set()
        live_grants: list[InsightReportingWalletGrant] = []
        for grant in grants:
            key = (grant.wallet_id, grant.ownership_epoch_id)
            if (
                key in seen_grants
                or grant.permission_kind != "wallet_evidence_read"
                or not _valid_identity(grant.grant_id)
                or not _valid_identity(grant.wallet_id)
                or not _valid_identity(grant.ownership_epoch_id)
                or not _valid_interval(grant.starts_at, grant.expires_at)
                or not _valid_interval(grant.evidence_from, grant.evidence_until)
                or (
                    grant.revoked_at is not None
                    and (
                        not isinstance(grant.revoked_at, datetime)
                        or grant.revoked_at.tzinfo is not None
                    )
                )
            ):
                _deny()
            seen_grants.add(key)
            if _live(grant.starts_at, grant.expires_at, grant.revoked_at, now):
                live_grants.append(grant)
        if {grant.wallet_id for grant in live_grants} != requested_wallets:
            _deny()

        history = (
            (
                await session.execute(
                    select(InsightWalletOwnershipEpoch).where(
                        col(InsightWalletOwnershipEpoch.wallet_id).in_(
                            requested_wallets
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        by_wallet: dict[str, list[InsightWalletOwnershipEpoch]] = {
            wallet_id: [] for wallet_id in requested_wallets
        }
        for epoch in history:
            if (
                epoch.wallet_id not in by_wallet
                or not _valid_identity(epoch.ownership_epoch_id)
                or not _valid_identity(epoch.owner_boundary_id)
                or type(epoch.history_complete) is not bool
                or not epoch.history_complete
                or not _valid_interval(epoch.evidence_from, epoch.evidence_until)
            ):
                _deny()
            by_wallet[epoch.wallet_id].append(epoch)
        by_id: dict[tuple[str, str], InsightWalletOwnershipEpoch] = {}
        for wallet_id, epochs in by_wallet.items():
            epochs.sort(key=lambda epoch: epoch.evidence_from)
            if not epochs:
                _deny()
            previous_until: datetime | None = None
            for epoch in epochs:
                if (wallet_id, epoch.ownership_epoch_id) in by_id or (
                    previous_until is not None and epoch.evidence_from != previous_until
                ):
                    _deny()
                by_id[(wallet_id, epoch.ownership_epoch_id)] = epoch
                previous_until = epoch.evidence_until

        authorized_epochs: list[AuthorizedOwnershipEpoch] = []
        for grant in live_grants:
            matched_epoch = by_id.get((grant.wallet_id, grant.ownership_epoch_id))
            if (
                matched_epoch is None
                or grant.evidence_from < matched_epoch.evidence_from
                or grant.evidence_until > matched_epoch.evidence_until
            ):
                _deny()
            authorized_epochs.append(
                AuthorizedOwnershipEpoch(
                    wallet_id=grant.wallet_id,
                    ownership_epoch_id=grant.ownership_epoch_id,
                    evidence_from=_aware_utc(grant.evidence_from),
                    evidence_until=_aware_utc(grant.evidence_until),
                )
            )
        scope = Scope(
            wallet_ids=requested_wallets,
            authorized_ownership_epochs=tuple(
                sorted(
                    authorized_epochs,
                    key=lambda item: (
                        item.wallet_id,
                        item.evidence_from,
                        item.ownership_epoch_id,
                    ),
                )
            ),
            allow_unknown_wallet_counts=include_unknown,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503, detail="insight_authority_unavailable"
        ) from exc
    session.info[_SCOPE_KEY] = (scope, _scope_fingerprint(scope))
    return scope
