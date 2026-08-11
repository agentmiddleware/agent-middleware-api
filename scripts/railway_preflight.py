#!/usr/bin/env python3
"""Railway deploy preflight: migration-head parity + live posture check.

Two independent checks, each skipped when its ordinary input is absent.
Explicit ``--public-db`` mode is an exception and fails closed when absent:

``--db`` (needs ``DATABASE_URL``)
    Compare the Alembic head revision in this tree against the
    ``alembic_version`` row in the target database. A tree that is ahead of
    the deployed schema is the failure mode that produces 500s on the first
    request touching a new table (see ``refresh_tokens`` / ``/v1/auth/refresh``).
    Also flags a database bootstrapped with ``create_all`` (tables present,
    no ``alembic_version`` row) — that needs a one-time ``alembic stamp head``
    before ``RUN_MIGRATIONS_ON_START=true`` is safe.

``--public-db`` (needs ``DATABASE_PUBLIC_URL``)
    Select the explicit public PostgreSQL URL for an off-platform database
    check, such as GitHub Actions after ``railway up``. This never falls back
    to ``DATABASE_URL``; a missing or private-looking value fails closed.

``--live`` (needs ``PUBLIC_URL`` or ``--url``)
    Probe the deployed service and assert the production posture the SOP
    requires: healthy, no memory fallback, proof surfaces and dogfood off, no
    dependency listed unhealthy. ``--expected-version`` and
    ``--expected-commit-sha`` add exact release-identity checks against both
    ``/health`` and ``/health/dependencies`` for the post-deploy gate; the
    commit expectation must be a full 40-character SHA.

Exit code is non-zero if any *executed* check fails, so this works as a
release gate. Skipped checks never fail the run; ``--strict`` turns a skip
into a failure for CI, where both inputs are expected.

Usage::

    # Before `railway up`, with the service env loaded:
    railway run python scripts/railway_preflight.py

    # Schema parity only:
    DATABASE_URL=postgresql://... python scripts/railway_preflight.py --db

    # Schema parity from an off-platform runner:
    DATABASE_PUBLIC_URL=postgresql://... \
      python scripts/railway_preflight.py --db --public-db --strict

    # Post-deploy verification only:
    python scripts/railway_preflight.py --live --url https://api.example.com \
      --expected-version 1.3.0 \
      --expected-commit-sha 0123456789abcdef0123456789abcdef01234567

See docs/deploy-railway.md.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.db_urls import as_sqlalchemy_url  # noqa: E402


OK = "[preflight] PASS"
BAD = "[preflight] FAIL"
SKIP = "[preflight] SKIP"


def _tree_head() -> str:
    """Alembic head revision for the migration scripts in this tree."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise RuntimeError(
            f"expected exactly one Alembic head, found {len(heads)}: {sorted(heads)}"
        )
    return heads[0]


async def _db_state(url: str) -> tuple[list[str], bool]:
    """Return (applied revisions, whether the DB has any app tables)."""
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(as_sqlalchemy_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if "alembic_version" not in table_names:
                return [], bool(table_names)
            rows = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return sorted(r[0] for r in rows), bool(table_names)
    finally:
        await engine.dispose()


def check_db(url: str) -> bool:
    head = _tree_head()
    applied, has_tables = asyncio.run(_db_state(url))

    if not applied:
        if has_tables:
            print(
                f"{BAD} database has tables but no alembic_version row "
                f"(create_all bootstrap). Run `alembic stamp head` once, then "
                f"enable RUN_MIGRATIONS_ON_START=true."
            )
        else:
            print(
                f"{BAD} database is empty and unmigrated (tree head {head}). "
                f"Run `alembic upgrade head` or set RUN_MIGRATIONS_ON_START=true."
            )
        return False

    if applied == [head]:
        print(f"{OK} schema at tree head {head}")
        return True

    print(
        f"{BAD} migration drift: tree head is {head}, database is at "
        f"{', '.join(applied)}. Deploying now ships code whose tables do not "
        f"exist yet. Run `alembic upgrade head` against the target database "
        f"(or set RUN_MIGRATIONS_ON_START=true so the entrypoint does it)."
    )
    return False


def _public_database_url(environment: Mapping[str, str] | None = None) -> str:
    """Load an explicitly public PostgreSQL URL without rendering its value."""
    values = os.environ if environment is None else environment
    url = values.get("DATABASE_PUBLIC_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_PUBLIC_URL is required")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(
            "DATABASE_PUBLIC_URL must be a valid public PostgreSQL URL"
        ) from exc
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_PUBLIC_URL must be a public PostgreSQL URL")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(".internal"):
        raise ValueError("DATABASE_PUBLIC_URL must not use a private or local hostname")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("DATABASE_PUBLIC_URL must not use a private or local address")
    return url


def check_live(
    url: str,
    *,
    expected_version: str | None = None,
    expected_commit_sha: str | None = None,
) -> bool:
    import httpx

    base = url.rstrip("/")
    try:
        resp = httpx.get(f"{base}/health/dependencies", timeout=30)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # network, non-2xx, or non-JSON — all disqualifying
        print(f"{BAD} {base}/health/dependencies unreachable: {exc}")
        return False

    failures: list[str] = []

    if body.get("status") != "healthy":
        failures.append(f"status={body.get('status')!r}, expected 'healthy'")

    production_like = body.get("production_like")
    if production_like is not True:
        failures.append(
            f"production_like={production_like!r} — ENVIRONMENT must engage "
            "production trust guardrails"
        )

    unhealthy = body.get("unhealthy") or []
    if unhealthy:
        failures.append(f"unhealthy dependencies: {unhealthy}")

    degradation = body.get("runtime_degradation") or {}
    durable = degradation.get("durable_state") or {}
    if durable.get("fell_back_to_memory"):
        failures.append(
            "durable state fell back to memory — DATABASE_URL / STATE_BACKEND "
            "are not taking effect"
        )

    if body.get("enable_proof_surfaces"):
        failures.append("enable_proof_surfaces=true — must be false in production")

    dogfood = body.get("enable_dogfood_tool")
    if dogfood is not False:
        failures.append(
            f"enable_dogfood_tool={dogfood!r} — must be explicitly false in production"
        )

    identity_reports = [("/health/dependencies", body)]
    if expected_version is not None or expected_commit_sha is not None:
        try:
            liveness_resp = httpx.get(f"{base}/health", timeout=30)
            liveness_resp.raise_for_status()
            identity_reports.append(("/health", liveness_resp.json()))
        except Exception as exc:
            failures.append(f"{base}/health unreachable: {exc}")

    if expected_version is not None:
        for endpoint, report in identity_reports:
            version = report.get("version")
            if version != expected_version:
                failures.append(
                    f"{endpoint} version={version!r}, expected exact version "
                    f"{expected_version!r}"
                )

    normalized_expected_sha = None
    if expected_commit_sha is not None:
        normalized_expected_sha = expected_commit_sha.lower()
        if re.fullmatch(r"[0-9a-f]{40}", normalized_expected_sha) is None:
            failures.append(
                "expected commit SHA must be the full 40-character hexadecimal SHA"
            )
        else:
            for endpoint, report in identity_reports:
                commit_sha = report.get("commit_sha")
                if commit_sha != normalized_expected_sha:
                    failures.append(
                        f"{endpoint} commit_sha={commit_sha!r}, expected exact SHA "
                        f"{normalized_expected_sha!r}"
                    )

    if failures:
        for item in failures:
            print(f"{BAD} {item}")
        return False

    displayed_version = body.get("version") or "unknown"
    displayed_commit_sha = body.get("commit_sha")
    displayed_sha = f", sha={displayed_commit_sha}" if displayed_commit_sha else ""
    print(
        f"{OK} {base} healthy (v{displayed_version}{displayed_sha}, "
        "proof_surfaces=false, dogfood_tool=false, no memory fallback)"
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--db", action="store_true", help="run only the migration-parity check"
    )
    parser.add_argument(
        "--live", action="store_true", help="run only the live posture check"
    )
    parser.add_argument(
        "--public-db",
        action="store_true",
        help=(
            "use explicit $DATABASE_PUBLIC_URL for an off-platform DB check; "
            "missing or private values fail closed"
        ),
    )
    parser.add_argument(
        "--url",
        default=os.getenv("PUBLIC_URL", ""),
        help="service origin for --live (default: $PUBLIC_URL)",
    )
    parser.add_argument(
        "--expected-version",
        default="",
        help="exact application version required from --live",
    )
    parser.add_argument(
        "--expected-commit-sha",
        default="",
        help="full 40-character commit SHA required from --live",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat a skipped check as a failure (for CI)",
    )
    args = parser.parse_args(argv)

    # Neither flag given: run whatever the environment supports.
    run_db = args.db or not (args.db or args.live)
    run_live = args.live or not (args.db or args.live)

    results: list[bool] = []

    if run_db:
        database_url_load_failed = False
        try:
            database_url = (
                _public_database_url()
                if args.public_db
                else os.getenv("DATABASE_URL", "").strip()
            )
        except ValueError as exc:
            print(f"{BAD} migration parity: {exc}")
            results.append(False)
            database_url_load_failed = True
            database_url = ""
        if database_url:
            try:
                results.append(check_db(database_url))
            except Exception:
                source = "DATABASE_PUBLIC_URL" if args.public_db else "DATABASE_URL"
                print(
                    f"{BAD} migration parity: {source} connection or schema "
                    "check failed"
                )
                results.append(False)
        elif not database_url_load_failed:
            print(f"{SKIP} migration parity: DATABASE_URL not set")
            results.append(not args.strict)

    if run_live:
        if args.url:
            results.append(
                check_live(
                    args.url,
                    expected_version=args.expected_version or None,
                    expected_commit_sha=args.expected_commit_sha or None,
                )
            )
        else:
            print(f"{SKIP} live posture: no PUBLIC_URL and no --url")
            results.append(not args.strict)

    if all(results):
        print("[preflight] all checks passed")
        return 0
    print("[preflight] preflight failed — do not deploy")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
