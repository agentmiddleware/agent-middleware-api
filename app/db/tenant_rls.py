"""PostgreSQL row-level security scope for wallet-scoped tables.

Migration ``047_tenant_rls`` enables and FORCEs row-level security on the
tables in :data:`RLS_TABLES`. Each policy admits a row only when

* its owning wallet column equals ``app.current_wallet_id``, or
* ``app.rls_bypass`` is ``'on'`` (the explicit admin mechanism).

An unset or empty ``app.current_wallet_id`` matches nothing, so a connection
that sets neither setting sees and writes no rows.

This module decides what those two settings are for each transaction:

* ``TENANT_RLS_MODE=enforce`` — a session ``after_begin`` hook runs
  ``set_config(..., true)`` (``SET LOCAL`` semantics, reset at commit or
  rollback, so a pooled connection never carries a wallet into the next
  checkout) from the scope bound by :func:`bind_wallet_scope` or
  :func:`rls_admin_scope`. No scope means fail closed.
* ``TENANT_RLS_MODE=off`` (default) — every app connection is opened with
  ``app.rls_bypass=on`` as a startup parameter, so the policies are inert for
  the app exactly as before the migration, while any other client connecting
  as a policy-bound role still sees no rows.

What this is, and is not: the policies are defense in depth against an
application query that forgets its wallet filter. They are not a boundary
against code that can already run SQL as the runtime role — such code can set
either setting itself. See ``docs/tenant-rls.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session, SessionTransaction

from ..core.config import get_settings

logger = logging.getLogger(__name__)

WALLET_SETTING = "app.current_wallet_id"
BYPASS_SETTING = "app.rls_bypass"
POLICY_NAME = "amw_tenant_isolation"

# Table -> owning wallet columns. A row is visible when ANY listed column
# matches the current wallet. Frozen copy of the list in migration
# 047_tenant_rls; tests/test_tenant_rls.py keeps the two in step.
RLS_TABLES: dict[str, tuple[str, ...]] = {
    "api_keys": ("wallet_id",),
    "billing_alerts": ("wallet_id",),
    "daily_balance_snapshots": ("wallet_id",),
    "human_approvals": ("wallet_id",),
    "idempotency_records": ("wallet_id",),
    "key_rotation_logs": ("wallet_id",),
    "kyc_verifications": ("wallet_id",),
    "ledger_entries": ("wallet_id",),
    "mcp_dispatch_attempts": ("wallet_id",),
    "permit_requests": ("issuer_wallet_id", "subject_wallet_id"),
    "permits": ("issuer_wallet_id", "subject_wallet_id"),
    "policy_bundles": ("wallet_id",),
    "quotes": ("wallet_id",),
    "receipts": ("wallet_id",),
    "refresh_tokens": ("wallet_id",),
}


@dataclass(frozen=True)
class RlsScope:
    """What the next transaction may see: one wallet, or everything."""

    wallet_id: str | None = None
    admin_reason: str | None = None

    @property
    def bypass(self) -> bool:
        return self.admin_reason is not None


_RLS_SCOPE: ContextVar[RlsScope | None] = ContextVar("tenant_rls_scope", default=None)


def current_rls_scope() -> RlsScope | None:
    return _RLS_SCOPE.get()


def bind_wallet_scope(
    wallet_id: str | None, *, admin_reason: str | None = None
) -> None:
    """Bind the authenticated caller's scope for the rest of this task.

    Called once per request by the auth dependency. The binding lives in the
    request task's context, so it never leaks into another request.
    """
    if admin_reason is not None:
        _RLS_SCOPE.set(RlsScope(admin_reason=admin_reason))
    elif wallet_id:
        _RLS_SCOPE.set(RlsScope(wallet_id=wallet_id))
    else:
        _RLS_SCOPE.set(None)


@contextmanager
def rls_admin_scope(reason: str) -> Iterator[None]:
    """Explicitly bypass wallet policies for transactions begun inside.

    Use only for paths that are cross-wallet by design: resolving which
    wallet an API key belongs to, bootstrap-admin requests, and operator
    maintenance jobs. ``reason`` is required so every call site names why.
    """
    if not reason:
        raise ValueError("rls_admin_scope requires a reason")
    token = _RLS_SCOPE.set(RlsScope(admin_reason=reason))
    try:
        yield
    finally:
        _RLS_SCOPE.reset(token)


def rls_admin_route(reason: str) -> Callable[[], Awaitable[None]]:
    """FastAPI dependency binding the admin bypass for one unauthenticated route.

    For routes with no caller wallet that must still write covered tables:
    anonymous key minting and signature-verified provider webhooks. Async on
    purpose: a sync dependency runs in a worker thread whose context binding
    would not reach the endpoint.
    """
    if not reason:
        raise ValueError("rls_admin_route requires a reason")

    async def bind_rls_admin_scope() -> None:
        bind_wallet_scope(None, admin_reason=reason)

    return bind_rls_admin_scope


@contextmanager
def rls_wallet_scope(wallet_id: str) -> Iterator[None]:
    """Narrow transactions begun inside to one wallet (temporary binding)."""
    if not wallet_id:
        raise ValueError("rls_wallet_scope requires a wallet_id")
    token = _RLS_SCOPE.set(RlsScope(wallet_id=wallet_id))
    try:
        yield
    finally:
        _RLS_SCOPE.reset(token)


def tenant_rls_enforced() -> bool:
    return get_settings().TENANT_RLS_MODE == "enforce"


def scope_settings(scope: RlsScope | None) -> dict[str, str]:
    """The two setting values for ``scope``; empty wallet means fail closed."""
    if scope is None:
        return {"wallet": "", "bypass": "off"}
    if scope.bypass:
        return {"wallet": "", "bypass": "on"}
    return {"wallet": scope.wallet_id or "", "bypass": "off"}


_SET_SCOPE_SQL = text(
    f"SELECT set_config('{WALLET_SETTING}', :wallet, true), "
    f"set_config('{BYPASS_SETTING}', :bypass, true)"
)


class TenantScopedSession(Session):
    """Sync session class behind the app's AsyncSession factory.

    A subclass, so the ``after_begin`` hook below applies to app sessions
    only and not to every SQLAlchemy session in the process (tests, Alembic).
    """


@event.listens_for(TenantScopedSession, "after_begin")
def _apply_rls_scope(
    session: Session,
    transaction: SessionTransaction,
    connection: Connection,
) -> None:
    if connection.dialect.name != "postgresql" or not tenant_rls_enforced():
        return
    # Inside the transaction just begun: set_config(..., is_local=true) is
    # SET LOCAL, discarded at commit/rollback.
    connection.execute(_SET_SCOPE_SQL, scope_settings(current_rls_scope()))


def engine_connect_args(db_url: str) -> dict[str, Any]:
    """Startup parameters that opt app connections out of RLS in off mode.

    In enforce mode nothing is set at connection level: the per-transaction
    hook is the only source of either setting.
    """
    if not db_url.startswith("postgresql") or tenant_rls_enforced():
        return {}
    if "+asyncpg" in db_url:
        return {"server_settings": {BYPASS_SETTING: "on"}}
    return {"options": f"-c {BYPASS_SETTING}=on"}


class TenantRlsPostureError(RuntimeError):
    """Raised when enforce mode is requested but the database cannot honor it."""


_POSTURE_SQL = text(
    """
    SELECT r.rolname, r.rolsuper, r.rolbypassrls
    FROM pg_roles r WHERE r.rolname = current_user
    """
)
_TABLES_SQL = text(
    """
    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
           pg_get_userbyid(c.relowner) AS owner
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = current_schema() AND c.relkind = 'r'
      AND c.relname = ANY(:tables)
    """
)


async def check_tenant_rls_posture(engine: AsyncEngine) -> dict[str, Any]:
    """Report whether the runtime role is actually bound by the policies.

    Superusers and BYPASSRLS roles skip every policy, FORCE included, so in
    enforce mode either one turns isolation into a claim the database does
    not make; that raises :class:`TenantRlsPostureError`. A role that owns
    the tables is still bound (FORCE) but could ``ALTER TABLE ... NO FORCE``,
    so it is reported, not refused.
    """
    settings = get_settings()
    report: dict[str, Any] = {"mode": settings.TENANT_RLS_MODE}
    if engine.dialect.name != "postgresql":
        report["dialect"] = engine.dialect.name
        report["effective"] = False
        return report

    async with engine.connect() as conn:
        role = (await conn.execute(_POSTURE_SQL)).one()
        rows = (await conn.execute(_TABLES_SQL, {"tables": list(RLS_TABLES)})).all()
    tables = {row.relname: row for row in rows}
    not_forced = sorted(
        name
        for name in RLS_TABLES
        if name not in tables
        or not (tables[name].relrowsecurity and tables[name].relforcerowsecurity)
    )
    owned = sorted(name for name, row in tables.items() if row.owner == role.rolname)
    bypasses = bool(role.rolsuper or role.rolbypassrls)
    report.update(
        role=role.rolname,
        superuser=bool(role.rolsuper),
        bypassrls=bool(role.rolbypassrls),
        owns_rls_tables=owned,
        tables_without_forced_rls=not_forced,
        effective=(
            settings.TENANT_RLS_MODE == "enforce" and not bypasses and not not_forced
        ),
    )

    if settings.TENANT_RLS_MODE != "enforce":
        return report
    problems: list[str] = []
    if bypasses:
        problems.append(
            f"runtime role {role.rolname!r} is "
            + ("SUPERUSER" if role.rolsuper else "BYPASSRLS")
            + " and skips every row-level policy"
        )
    if not_forced:
        problems.append(
            "row-level security is not enabled and forced on: "
            + ", ".join(not_forced)
            + " (run alembic upgrade head)"
        )
    if problems:
        raise TenantRlsPostureError(
            "TENANT_RLS_MODE=enforce cannot be honored: "
            + "; ".join(problems)
            + ". Connect as a NOSUPERUSER NOBYPASSRLS non-owner role "
            "(docs/tenant-rls.md) or set TENANT_RLS_MODE=off."
        )
    if owned:
        logger.warning(
            "tenant_rls_runtime_role_owns_tables role=%s tables=%s: FORCE keeps "
            "the owner bound, but an owner can ALTER TABLE ... NO FORCE; use a "
            "non-owner runtime role",
            role.rolname,
            ",".join(owned),
        )
    return report
