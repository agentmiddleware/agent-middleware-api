#!/usr/bin/env python3
"""Railway deploy preflight: customer manifest + deploy posture checks.

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

``--manifest`` (optional non-secret JSON)
    Bind the checks to one managed single-tenant deployment. The manifest
    supplies the public origin, expected commit, Alembic revision, and signing
    key id/public fingerprint. Its expected commit and revision must match this
    checkout, and the live service must publish the configured signing key.
    Existing invocations without a manifest keep their current behavior.

``--manifest-only`` (requires ``--manifest``)
    Validate the candidate manifest against this clean checkout without probing
    the currently deployed release. Use this before an upgrade, because the
    running service still reports the previous commit until deployment.

Exit code is non-zero if any *executed* check fails, so this works as a
release gate. Skipped checks never fail the run; ``--strict`` turns a skip
into a failure for CI, where both inputs are expected.

Usage::

    # Before `railway up`, when the database is reachable from this machine:
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

    # Managed single-tenant gate (URL and commit come from the manifest):
    python scripts/railway_preflight.py --live --strict \
      --manifest /path/to/customer.production.json

    # Candidate source/manifest binding before deployment (no network checks):
    python scripts/railway_preflight.py --manifest-only \
      --manifest /path/to/customer.production.json

See docs/deploy-railway.md.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.db_urls import as_sqlalchemy_url  # noqa: E402


OK = "[preflight] PASS"
BAD = "[preflight] FAIL"
SKIP = "[preflight] SKIP"

# Local proof-infrastructure tool ids that must never appear in a production
# deployment's public discovery (see app/services/dogfood_tool.py).
_DOGFOOD_TOOL_IDS = frozenset({"partner.notes.write", "partner.notes.count"})

MANIFEST_SCHEMA_VERSION = "1.0"
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "customer_slug",
        "railway_project_id",
        "environment",
        "region",
        "public_url",
        "signing_key_id",
        "signing_public_key_sha256",
        "expected_commit_sha",
        "expected_alembic_revision",
    }
)
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_SAFE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}")
_ALEMBIC_REVISION_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,63}")
_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class ManifestError(ValueError):
    """Raised when a customer deployment manifest is not safe to use."""


class CustomerManifest(NamedTuple):
    schema_version: str
    customer_slug: str
    railway_project_id: str
    environment: str
    region: str
    public_url: str
    signing_key_id: str
    signing_public_key_sha256: str
    expected_commit_sha: str
    expected_alembic_revision: str


def _tree_commit_sha() -> str:
    """Return the full commit SHA for the intended release checkout."""
    try:
        commit_sha = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            .stdout.strip()
            .lower()
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to resolve the tree commit SHA") from exc
    if _COMMIT_SHA_RE.fullmatch(commit_sha) is None:
        raise RuntimeError("tree commit SHA is not a full hexadecimal SHA")
    return commit_sha


def _tree_is_clean() -> bool:
    """Return whether ``railway up`` would start from a clean Git checkout."""
    try:
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=normal",
                "--ignore-submodules=none",
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to inspect the release checkout") from exc
    return not status.strip()


def _canonical_public_url(value: str) -> str:
    """Validate and return a canonical public HTTPS origin."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ManifestError("manifest public_url must be a valid HTTPS origin") from exc

    hostname = parsed.hostname or ""
    labels = hostname.split(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or hostname != hostname.lower()
        or len(hostname) > 253
        or len(labels) < 2
        or any(_DNS_LABEL_RE.fullmatch(label) is None for label in labels)
        or hostname == "localhost"
        or hostname.endswith(".internal")
    ):
        raise ManifestError(
            "manifest public_url must be a canonical public HTTPS origin"
        )

    canonical = f"https://{hostname}"
    if value.rstrip("/") != canonical:
        raise ManifestError(
            "manifest public_url must be a canonical public HTTPS origin"
        )
    return canonical


def _load_customer_manifest(path: str | Path) -> CustomerManifest:
    """Load a strict, non-secret customer deployment manifest."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest must be readable UTF-8 JSON") from exc

    if not isinstance(document, dict):
        raise ManifestError("manifest root must be a JSON object")

    fields = set(document)
    missing = sorted(_MANIFEST_FIELDS - fields)
    if missing:
        raise ManifestError(f"manifest missing required fields: {', '.join(missing)}")
    unexpected = fields - _MANIFEST_FIELDS
    if unexpected:
        raise ManifestError("manifest contains unsupported fields")
    if any(not isinstance(document[field], str) for field in _MANIFEST_FIELDS):
        raise ManifestError("every manifest field must be a JSON string")

    if document["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(
            f"manifest schema_version must be {MANIFEST_SCHEMA_VERSION!r}"
        )
    if _SLUG_RE.fullmatch(document["customer_slug"]) is None:
        raise ManifestError("manifest customer_slug must be a lowercase DNS-style slug")
    try:
        project_id = UUID(document["railway_project_id"])
    except ValueError as exc:
        raise ManifestError(
            "manifest railway_project_id must be a canonical UUID"
        ) from exc
    if str(project_id) != document["railway_project_id"] or project_id.int == 0:
        raise ManifestError("manifest railway_project_id must be a canonical UUID")
    if _SLUG_RE.fullmatch(document["environment"]) is None:
        raise ManifestError("manifest environment must be a lowercase DNS-style slug")
    if _SLUG_RE.fullmatch(document["region"]) is None:
        raise ManifestError("manifest region must be a lowercase DNS-style slug")
    public_url = _canonical_public_url(document["public_url"])
    if _SAFE_ID_RE.fullmatch(document["signing_key_id"]) is None:
        raise ManifestError(
            "manifest signing_key_id must be a lowercase safe identifier"
        )
    if _SHA256_RE.fullmatch(document["signing_public_key_sha256"]) is None:
        raise ManifestError(
            "manifest signing_public_key_sha256 must be a lowercase SHA-256 digest"
        )
    if _COMMIT_SHA_RE.fullmatch(document["expected_commit_sha"]) is None:
        raise ManifestError(
            "manifest expected_commit_sha must be a lowercase full 40-character SHA"
        )
    if _ALEMBIC_REVISION_RE.fullmatch(document["expected_alembic_revision"]) is None:
        raise ManifestError(
            "manifest expected_alembic_revision must be a lowercase Alembic revision"
        )

    return CustomerManifest(
        schema_version=document["schema_version"],
        customer_slug=document["customer_slug"],
        railway_project_id=document["railway_project_id"],
        environment=document["environment"],
        region=document["region"],
        public_url=public_url,
        signing_key_id=document["signing_key_id"],
        signing_public_key_sha256=document["signing_public_key_sha256"],
        expected_commit_sha=document["expected_commit_sha"],
        expected_alembic_revision=document["expected_alembic_revision"],
    )


def _matches_ed25519_public_key(entry: object, expected_sha256: str) -> bool:
    """Validate published Ed25519 material and compare its public fingerprint."""
    if not isinstance(entry, dict) or entry.get("alg") != "Ed25519":
        return False
    public_key_b64 = entry.get("public_key_b64")
    if not isinstance(public_key_b64, str):
        return False
    try:
        raw_public_key = base64.b64decode(public_key_b64, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw_public_key) == 32 and (
        hashlib.sha256(raw_public_key).hexdigest() == expected_sha256
    )


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
    expected_signing_key_id: str | None = None,
    expected_signing_public_key_sha256: str | None = None,
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

    # Build provenance: did this image come through the documented release
    # path? The operator uploads an archive-stamped exact-SHA release context;
    # the Dockerfile requires that stamp. Anything other than "stamped" means
    # the running image was built by something else — a Railway rebuild from a
    # connected GitHub source, for instance, which a plain variable write is
    # enough to trigger.
    #
    # Key presence, not truthiness, for the same reason as the dogfood check
    # below: a genuinely absent key means the deployed image predates this
    # field. That earns a note only during a pre-mutation posture check with no
    # release identity expectation; an exact-release check must prove stamped
    # provenance. A
    # *published* null is a different thing entirely. The field exists and does
    # not say "stamped", so it must fail closed like any other non-stamped
    # value. Once a stamped release is out, the key is always present.
    if "build_provenance" not in body:
        if expected_commit_sha is not None:
            failures.append(
                "build_provenance is absent — exact releases must report "
                "'stamped' provenance from the documented railway up path"
            )
        else:
            print(
                "[preflight] NOTE build_provenance absent from "
                "/health/dependencies — deployed image predates this field; "
                "provenance not verified"
            )
    else:
        provenance = body["build_provenance"]
        if provenance != "stamped":
            failures.append(
                f"build_provenance={provenance!r} — the running image was not "
                "built from the documented archive-stamped release context; it "
                "did not come through the documented release path"
            )

    # Key presence, not truthiness: a *published* null must still fail the
    # exactly-false requirement below — only a genuinely absent key (the
    # post-#348 public projection) earns the discovery fallback.
    if "enable_dogfood_tool" not in body:
        # The public /health/dependencies projection stopped publishing the
        # dogfood flag when proof surfaces are unmounted (the flag described
        # nothing a caller could reach — see build_public_dependency_report).
        # Verify the observable posture instead: the dogfood tools must not
        # be registered in public discovery.
        try:
            discover_resp = httpx.get(f"{base}/v1/discover", timeout=30)
            discover_resp.raise_for_status()
            discover_body = discover_resp.json()
        except Exception as exc:
            failures.append(
                "enable_dogfood_tool is absent from /health/dependencies and "
                f"/v1/discover could not be checked instead: {exc}"
            )
        else:
            tools = (
                discover_body.get("mcp_tools")
                if isinstance(discover_body, dict)
                else None
            )
            if not isinstance(tools, list) or not all(
                isinstance(tool, dict) for tool in tools
            ):
                # Fail closed on an unrecognized shape: treating it as "no
                # tools" would let a renamed field or an error page silently
                # pass the release gate.
                failures.append(
                    "enable_dogfood_tool is absent from /health/dependencies "
                    "and /v1/discover returned an unrecognized shape (no "
                    "mcp_tools list) — cannot verify dogfood posture"
                )
            else:
                # Check service_id and name independently: a benign
                # service_id must not mask a dogfood name (or vice versa).
                # Non-string identifiers are an unrecognized shape, not a
                # clean catalog.
                leaked_ids: set[str] = set()
                malformed_identifier = False
                for tool in tools:
                    for field in ("service_id", "name"):
                        value = tool.get(field)
                        if value is None:
                            continue
                        if not isinstance(value, str):
                            malformed_identifier = True
                            continue
                        if value in _DOGFOOD_TOOL_IDS:
                            leaked_ids.add(value)
                if malformed_identifier:
                    failures.append(
                        "/v1/discover tool identifiers must be strings — "
                        "cannot verify dogfood posture"
                    )
                if leaked_ids:
                    failures.append(
                        "dogfood tools exposed in public discovery: "
                        f"{sorted(leaked_ids)} — ENABLE_DOGFOOD_TOOL must be "
                        "false in production"
                    )
    elif body["enable_dogfood_tool"] is not False:
        dogfood = body["enable_dogfood_tool"]
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

    if expected_signing_key_id is not None:
        if (
            expected_signing_public_key_sha256 is None
            or _SHA256_RE.fullmatch(expected_signing_public_key_sha256) is None
        ):
            failures.append(
                "expected signing public-key fingerprint must be a lowercase "
                "SHA-256 digest"
            )

        health_signing_key_id = body.get("signing_key_id")
        dependencies = body.get("dependencies")
        if health_signing_key_id is None and isinstance(dependencies, dict):
            signing_key = dependencies.get("signing_key")
            if isinstance(signing_key, dict):
                health_signing_key_id = signing_key.get("key_id")

        if health_signing_key_id is not None:
            if health_signing_key_id != expected_signing_key_id:
                failures.append(
                    "live health signing key id does not match the customer manifest"
                )

        try:
            keys_resp = httpx.get(
                f"{base}/.well-known/trust-keys.json",
                timeout=30,
            )
            keys_resp.raise_for_status()
            key_document = keys_resp.json()
        except Exception:
            failures.append(
                "public trust-key document is unavailable; cannot verify the "
                "manifest signing key id"
            )
        else:
            published_keys = (
                key_document.get("keys") if isinstance(key_document, dict) else None
            )
            issuer = (
                key_document.get("issuer") if isinstance(key_document, dict) else None
            )
            document_alg = (
                key_document.get("alg") if isinstance(key_document, dict) else None
            )
            active_matches = (
                [
                    key
                    for key in published_keys
                    if isinstance(key, dict)
                    and key.get("kid") == expected_signing_key_id
                    and key.get("status") == "active"
                ]
                if isinstance(published_keys, list)
                else []
            )
            if issuer != base:
                failures.append(
                    "public trust-key issuer does not match the customer manifest URL"
                )
            if document_alg != "Ed25519":
                failures.append("public trust-key document must use Ed25519")
            if len(active_matches) != 1 or not _matches_ed25519_public_key(
                active_matches[0] if len(active_matches) == 1 else None,
                expected_signing_public_key_sha256 or "",
            ):
                failures.append(
                    "manifest signing key id is not published exactly once as an "
                    "active Ed25519 key with valid public material"
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
        "--manifest",
        default="",
        help=(
            "strict non-secret customer deployment manifest; supplies the live "
            "URL, commit SHA, Alembic revision, and signing key identity"
        ),
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help=(
            "validate --manifest against this clean release checkout without "
            "running database or live-service checks"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat a skipped check as a failure (for CI)",
    )
    args = parser.parse_args(argv)

    if args.manifest_only and not args.manifest:
        print(f"{BAD} --manifest-only requires --manifest")
        return 1
    if args.manifest_only and (
        args.db
        or args.live
        or args.public_db
        or args.expected_version
        or args.expected_commit_sha
    ):
        print(
            f"{BAD} --manifest-only cannot be combined with --db, --live, "
            "--public-db, or live release expectations"
        )
        return 1

    # Neither flag given: run whatever the environment supports.
    run_db = not args.manifest_only and (args.db or not (args.db or args.live))
    run_live = not args.manifest_only and (args.live or not (args.db or args.live))

    results: list[bool] = []
    manifest: CustomerManifest | None = None
    effective_url = args.url.strip()
    effective_commit_sha = args.expected_commit_sha.strip()

    if args.manifest:
        try:
            manifest = _load_customer_manifest(args.manifest)
            tree_head = _tree_head()
            tree_commit_sha = _tree_commit_sha()
            tree_is_clean = _tree_is_clean()
        except ManifestError as exc:
            print(f"{BAD} customer manifest: {exc}")
            return 1
        except Exception as exc:
            # Keep the cause: a missing dependency (no ``alembic`` on the
            # interpreter running this script) reads as a git problem otherwise.
            print(
                f"{BAD} customer manifest: unable to resolve checkout "
                f"provenance: {type(exc).__name__}: {exc}"
            )
            return 1

        if manifest.expected_alembic_revision != tree_head:
            print(f"{BAD} customer manifest Alembic revision does not match this tree")
            return 1
        if manifest.expected_commit_sha != tree_commit_sha:
            print(
                f"{BAD} customer manifest commit SHA does not match this "
                "release checkout"
            )
            return 1
        if not tree_is_clean:
            print(
                f"{BAD} customer manifest requires a clean release checkout; "
                "tracked or untracked changes are present"
            )
            return 1
        if effective_url and effective_url.rstrip("/") != manifest.public_url:
            print(f"{BAD} live URL does not match the customer manifest")
            return 1
        effective_url = manifest.public_url
        if (
            effective_commit_sha
            and effective_commit_sha.lower() != manifest.expected_commit_sha
        ):
            print(f"{BAD} expected commit SHA does not match the customer manifest")
            return 1
        effective_commit_sha = manifest.expected_commit_sha

    if args.manifest_only:
        print(f"{OK} customer manifest matches clean release checkout")
        return 0

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
        if effective_url:
            if manifest is not None:
                live_result = check_live(
                    effective_url,
                    expected_version=args.expected_version or None,
                    expected_commit_sha=effective_commit_sha or None,
                    expected_signing_key_id=manifest.signing_key_id,
                    expected_signing_public_key_sha256=(
                        manifest.signing_public_key_sha256
                    ),
                )
            else:
                live_result = check_live(
                    effective_url,
                    expected_version=args.expected_version or None,
                    expected_commit_sha=effective_commit_sha or None,
                )
            results.append(live_result)
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
