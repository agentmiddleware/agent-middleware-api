#!/usr/bin/env python3
"""Idempotently retire credentials that old workers can write during rollout.

Run this only after the previous Railway deployment has fully drained. The
025 migration performs the same scrub before a rolling deploy, but an old
worker can write a credential again while it is still serving traffic. This
post-deploy pass closes that race and verifies that no non-empty value remains.
It also revokes refresh-token rows that old workers can still write without the
API-key binding introduced by the published refresh-token migration.

The default command intentionally accepts only ``DATABASE_PUBLIC_URL`` for
legacy off-platform use. ``--private-db`` instead requires the API container's
Railway-private ``DATABASE_URL``. Neither mode falls back to the other URL or
renders a URL or stored value.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.db_urls import as_sqlalchemy_url  # noqa: E402


_LEGACY_TABLES = ("wallets", "service_registry")
_REQUIRED_COLUMNS = {
    "wallets": {"owner_key"},
    "service_registry": {"owner_key"},
    "refresh_tokens": {"key_id", "revoked"},
}
OK = "[owner-key-retirement] PASS"
BAD = "[owner-key-retirement] FAIL"


class OwnerKeyRetirementError(RuntimeError):
    """Fail-closed error that never includes a URL or stored credential."""


def load_public_database_url(
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return a validated public PostgreSQL URL without a private-URL fallback."""
    values = os.environ if environment is None else environment
    url = values.get("DATABASE_PUBLIC_URL", "").strip()
    if not url:
        raise OwnerKeyRetirementError("DATABASE_PUBLIC_URL is required")

    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise OwnerKeyRetirementError(
            "DATABASE_PUBLIC_URL must be a valid public PostgreSQL URL"
        ) from exc
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise OwnerKeyRetirementError(
            "DATABASE_PUBLIC_URL must be a public PostgreSQL URL"
        )
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(".internal"):
        raise OwnerKeyRetirementError(
            "DATABASE_PUBLIC_URL must not use a private or local hostname"
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise OwnerKeyRetirementError(
            "DATABASE_PUBLIC_URL must not use a private or local address"
        )
    return url


def load_private_database_url(
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return the Railway-private PostgreSQL URL without a public fallback."""
    values = os.environ if environment is None else environment
    url = values.get("DATABASE_URL", "").strip()
    if not url:
        raise OwnerKeyRetirementError("DATABASE_URL is required")

    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise OwnerKeyRetirementError(
            "DATABASE_URL must be a private Railway PostgreSQL URL"
        ) from exc
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme not in {
        "postgres",
        "postgresql",
        "postgresql+asyncpg",
    } or not hostname.endswith(".railway.internal"):
        raise OwnerKeyRetirementError(
            "DATABASE_URL must be a private Railway PostgreSQL URL"
        )
    # asyncpg accepts query-string connection overrides such as
    # ``?host=public-proxy&port=...``. Reject every query/fragment so the
    # validated authority is necessarily the authority used to connect.
    if parsed.query or parsed.fragment:
        raise OwnerKeyRetirementError(
            "DATABASE_URL must be a private Railway PostgreSQL URL"
        )
    return url


def _retirement_schema(sync_connection: Connection) -> dict[str, set[str]]:
    inspector = inspect(sync_connection)
    table_names = set(inspector.get_table_names())
    return {
        table: (
            {column["name"] for column in inspector.get_columns(table)}
            if table in table_names
            else set()
        )
        for table in _REQUIRED_COLUMNS
    }


async def retire_owner_keys(database_url: str) -> dict[str, int]:
    """Scrub owner keys and revoke unbound refresh tokens transactionally."""
    engine = create_async_engine(
        as_sqlalchemy_url(database_url),
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as connection:
            schema = await connection.run_sync(_retirement_schema)
            missing = [
                table
                for table, required in _REQUIRED_COLUMNS.items()
                if not required.issubset(schema[table])
            ]
            if missing:
                raise OwnerKeyRetirementError(
                    "expected post-drain retirement columns are missing"
                )

            if connection.dialect.name == "postgresql":
                await connection.execute(
                    text(
                        "LOCK TABLE wallets, service_registry, refresh_tokens "
                        "IN SHARE ROW EXCLUSIVE MODE"
                    )
                )

            scrubbed: dict[str, int] = {}
            for table in _LEGACY_TABLES:
                result = await connection.execute(
                    text(
                        f"UPDATE {table} SET owner_key = '' "
                        "WHERE owner_key IS NULL OR owner_key <> ''"
                    )
                )
                scrubbed[table] = max(0, int(result.rowcount or 0))

            refresh_result = await connection.execute(
                text(
                    "UPDATE refresh_tokens SET revoked = :revoked "
                    "WHERE key_id IS NULL AND revoked = :not_revoked"
                ),
                {"revoked": True, "not_revoked": False},
            )
            scrubbed["unbound_refresh_tokens"] = max(
                0, int(refresh_result.rowcount or 0)
            )

            remaining = 0
            for table in _LEGACY_TABLES:
                count = await connection.scalar(
                    text(
                        f"SELECT COUNT(*) FROM {table} "
                        "WHERE owner_key IS NULL OR owner_key <> ''"
                    )
                )
                remaining += int(count or 0)
            if remaining:
                raise OwnerKeyRetirementError(
                    "legacy owner_key retirement assertion failed for "
                    f"{remaining} row(s)"
                )

            unbound_refresh_tokens = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM refresh_tokens "
                    "WHERE key_id IS NULL AND revoked = :not_revoked"
                ),
                {"not_revoked": False},
            )
            if unbound_refresh_tokens:
                raise OwnerKeyRetirementError(
                    "unbound refresh-token retirement assertion failed for "
                    f"{int(unbound_refresh_tokens)} row(s)"
                )
            return scrubbed
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--private-db",
        action="store_true",
        help=(
            "require Railway-private $DATABASE_URL for an in-container run; "
            "never fall back to $DATABASE_PUBLIC_URL"
        ),
    )
    args = parser.parse_args([] if argv is None else argv)
    connection_kind = "private" if args.private_db else "public"
    try:
        database_url = (
            load_private_database_url()
            if args.private_db
            else load_public_database_url()
        )
        scrubbed = asyncio.run(retire_owner_keys(database_url))
    except OwnerKeyRetirementError as exc:
        print(f"{BAD} {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            f"{BAD} {connection_kind} database scrub or verification failed",
            file=sys.stderr,
        )
        return 1

    owner_keys = sum(scrubbed[table] for table in _LEGACY_TABLES)
    refresh_tokens = scrubbed["unbound_refresh_tokens"]
    print(
        f"{OK} scrubbed {owner_keys} compatibility value(s), revoked "
        f"{refresh_tokens} unbound refresh token(s); verified retirement state"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
