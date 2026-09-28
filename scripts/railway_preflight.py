#!/usr/bin/env python3
"""Railway deploy preflight: customer manifest + deploy posture checks.

Independent checks, each skipped when its ordinary input is absent.
Explicit ``--public-db`` and ``--runtime-posture`` modes are exceptions and
fail closed when their input is absent:

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
    to ``DATABASE_URL``; a missing or private-looking value fails closed. It
    always runs the database check, whatever other check is selected.

``--live`` (needs ``PUBLIC_URL`` or ``--url``)
    Probe the deployed service and assert the production posture the SOP
    requires: healthy, no memory fallback, proof surfaces off, any published
    dogfood flag exactly false, no dependency listed unhealthy, and every
    production tool catalog refusing unauthenticated reads with the
    application's own 401 ``missing_credentials`` refusal (the #444 Narrow
    lockdown). Only unauthenticated GETs are sent. The public projection does
    not publish the dogfood flags, so a ``--live``-only run does not verify
    the dogfood posture; ``--runtime-posture`` does, in the container.
    ``--expected-version`` and
    ``--expected-commit-sha`` add exact release-identity checks against both
    ``/health`` and ``/health/dependencies`` for the post-deploy gate; the
    commit expectation must be a full 40-character SHA.
    ``--expected-signing-key-id`` and ``--expected-signing-public-key-sha256``
    (given together, only with ``--live``, never with ``--manifest``, which
    already carries both) require the trust-key document to publish that key
    id exactly once as an active Ed25519 key with that public-key fingerprint.
    They serve a live gate run from a checkout other than the release, such
    as a rollback to a release whose own preflight predates the locked
    catalogs.

    Limitation (manifest or flags alike): this proves the key is *published*
    as active, not that the process *signs* with it. The public health
    report's signing_key entry carries only status and state; the key the
    process signs with is exposed only on the authenticated
    ``GET /v1/signing-keys/active``. A rotation by redeploy (new
    ``TRUST_SIGNING_PRIVATE_KEY_B64`` and ``TRUST_SIGNING_KEY_ID``) activates
    the new key id without retiring the old one
    (``SigningKeyService.ensure_active_key``), so both stay active and a
    stale expectation naming the old key still passes. After a rotation the
    old key must be retired before this check means anything, and the
    repository has no operator command for that yet: docs/key-management.md
    names ``POST /v1/admin/signing-keys/rotate``, which does not exist, and
    ``retire_key_metadata`` / ``rotate_active_key_metadata`` are service
    methods only. See the rollback section of docs/deploy-railway.md.

``--runtime-posture`` (run inside the deployed API container)
    Assert the dogfood posture that is no longer publicly observable: the
    public health projection omits the dogfood flags and the tool catalogs
    require credentials, so this reads the service's configuration from the
    process environment (never a ``.env`` file, and it fails when one exists
    where the service would read it). It requires a Railway runtime marker
    variable, a production-like ``ENVIRONMENT`` and both dogfood flags false,
    so it fails closed on a machine outside Railway.
    Release expectations and ``--manifest`` belong to ``--live`` and are
    rejected unless ``--live`` is also given.

``--railway-source-unbound`` (requires explicit target arguments)
    Read Railway's provider status and fail closed unless exactly one target
    environment and service report explicit null repository and image sources.
    This check does not change or disconnect provider settings.

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

    # Private dogfood posture, inside the deployed API container (an image
    # built before this flag existed needs the inline check in
    # docs/deploy-railway.md instead):
    railway ssh --service api-service --environment production -- \
      python scripts/railway_preflight.py --db --runtime-posture --strict

    # Read-only provider-source gate immediately before deployment:
    python scripts/railway_preflight.py --railway-source-unbound \
      --railway-project 11111111-1111-4111-8111-111111111111 \
      --railway-environment production --railway-service api-service

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
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.db_urls import as_sqlalchemy_url  # noqa: E402

if TYPE_CHECKING:
    import httpx


OK = "[preflight] PASS"
BAD = "[preflight] FAIL"
SKIP = "[preflight] SKIP"

# Tool catalogs that production-like boots must refuse to unauthenticated
# callers (#444 Narrow lockdown; see reject_anonymous_production_catalog in
# app/core/auth.py and SECURITY_LIMITATIONS.md). A stranger must not learn
# which tools exist.
_LOCKED_CATALOG_PATHS = (
    "/v1/discover",
    "/mcp/tools.json",
    "/mcp/tools",
    "/.well-known/mcp/tools.json",
)

# The error code in the body of that refusal (get_auth_context in
# app/core/auth.py raises {"detail": {"error": "missing_credentials", ...}}).
# A 401 from an edge, proxy, or platform layer has a different body and does
# not prove the application refused the read.
_CATALOG_REFUSAL_ERROR = "missing_credentials"

# Runtime flags that register local proof-infrastructure tools
# (partner.notes.write / partner.notes.count; see app/services/dogfood_tool.py).
_DOGFOOD_RUNTIME_FLAGS = ("ENABLE_DOGFOOD_TOOL", "ENABLE_DOGFOOD_SECOND_TOOL")

# Their names in the full /health/dependencies report (gather_dependency_report
# in app/core/health.py). The public projection omits both; when either is
# published it must be exactly false.
_PUBLISHED_DOGFOOD_FLAGS = ("enable_dogfood_tool", "enable_dogfood_second_tool")

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


def validate_railway_source_unbound(
    document: object,
    *,
    project_id: str,
    environment: str,
    service: str,
) -> bool:
    """Return whether one exact Railway service has no provider source."""
    if not isinstance(document, Mapping) or document.get("id") != project_id:
        return False

    environments = document.get("environments")
    if not isinstance(environments, Mapping):
        return False
    environment_edges = environments.get("edges")
    if not isinstance(environment_edges, list):
        return False

    matching_environments: list[Mapping[str, object]] = []
    for edge in environment_edges:
        if not isinstance(edge, Mapping):
            return False
        node = edge.get("node")
        if not isinstance(node, Mapping) or not isinstance(node.get("name"), str):
            return False
        if node["name"] == environment:
            matching_environments.append(node)
    if len(matching_environments) != 1:
        return False

    service_instances = matching_environments[0].get("serviceInstances")
    if not isinstance(service_instances, Mapping):
        return False
    service_edges = service_instances.get("edges")
    if not isinstance(service_edges, list):
        return False

    matching_services: list[Mapping[str, object]] = []
    for edge in service_edges:
        if not isinstance(edge, Mapping):
            return False
        node = edge.get("node")
        if not isinstance(node, Mapping) or not isinstance(
            node.get("serviceName"), str
        ):
            return False
        if node["serviceName"] == service:
            matching_services.append(node)
    if len(matching_services) != 1:
        return False

    source = matching_services[0].get("source")
    return (
        isinstance(source, Mapping)
        and "repo" in source
        and "image" in source
        and source["repo"] is None
        and source["image"] is None
    )


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one JSON object while rejecting ambiguous duplicate keys."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    """Reject Python JSON's non-standard NaN and infinity constants."""
    raise ValueError("non-standard JSON constant")


def check_railway_source_unbound(
    *, project_id: str, environment: str, service: str
) -> bool:
    """Fail closed unless Railway reports one explicitly unbound service."""
    command = [
        "railway",
        "status",
        "--project",
        project_id,
        "--environment",
        environment,
        "--json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            shell=False,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        print(f"{BAD} Railway service source could not be verified")
        return False

    if result.returncode != 0:
        print(f"{BAD} Railway service source could not be verified")
        return False
    try:
        document = json.loads(
            result.stdout,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        print(f"{BAD} Railway service source could not be verified")
        return False
    if not validate_railway_source_unbound(
        document,
        project_id=project_id,
        environment=environment,
        service=service,
    ):
        print(f"{BAD} Railway service source could not be verified")
        return False

    print(f"{OK} Railway service source is unbound")
    return True


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


def _is_catalog_refusal(response: "httpx.Response") -> bool:
    """Whether a 401 carries the application's own anonymous-catalog refusal.

    ``reject_anonymous_production_catalog`` (app/core/auth.py) refuses through
    ``get_auth_context``, whose body is
    ``{"detail": {"error": "missing_credentials", ...}}``. Anything else (no
    JSON, another shape, another error code) did not come from that code path.
    """
    try:
        body = response.json()
    except Exception:
        return False
    detail = body.get("detail") if isinstance(body, dict) else None
    return isinstance(detail, dict) and detail.get("error") == _CATALOG_REFUSAL_ERROR


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
    # exactly-false requirement. The full report publishes both dogfood
    # flags; each one that is published must be exactly false.
    for published_flag in _PUBLISHED_DOGFOOD_FLAGS:
        if published_flag in body and body[published_flag] is not False:
            failures.append(
                f"{published_flag}={body[published_flag]!r} — must be "
                "explicitly false in production"
            )
    dogfood_verified = body.get("enable_dogfood_tool") is False
    if "enable_dogfood_tool" not in body:
        # The public projection omits the flag (#348), and since the #444
        # lockdown the tool catalogs that used to stand in for it require
        # credentials. The dogfood state is not publicly observable, so say
        # so rather than report it as checked: --runtime-posture verifies it
        # inside the deployed API container.
        print(
            "[preflight] NOTE enable_dogfood_tool is not published and tool "
            "catalogs require credentials — the dogfood posture is private; "
            "verify it with --runtime-posture inside the deployed API container"
        )

    # Tool catalogs must refuse unauthenticated reads (#444). No credentials
    # are sent. A 2xx is the pre-lockdown public catalog. Any other status
    # (a redirect, 403, 404, 5xx) or an unreachable route cannot confirm the
    # lockdown, so it fails closed too. A 401 counts only when its body is
    # the application's own missing_credentials refusal: an edge or proxy
    # 401 in front of a public catalog must not satisfy the gate.
    for path in _LOCKED_CATALOG_PATHS:
        try:
            catalog_resp = httpx.get(f"{base}{path}", timeout=30)
        except Exception as exc:
            failures.append(
                f"{path} could not be checked for the locked-down catalog "
                f"posture: {exc}"
            )
            continue
        catalog_status = catalog_resp.status_code
        if catalog_status == 401:
            if _is_catalog_refusal(catalog_resp):
                continue
            failures.append(
                f"{path} answered 401 without the application's "
                f"{_CATALOG_REFUSAL_ERROR!r} refusal body — cannot confirm the "
                "locked-down catalog posture"
            )
            continue
        if 200 <= catalog_status < 300:
            failures.append(
                f"{path} is publicly readable (HTTP {catalog_status}) — "
                "production tool catalogs must refuse unauthenticated "
                "requests with 401"
            )
        else:
            failures.append(
                f"{path} answered an unauthenticated request with HTTP "
                f"{catalog_status}, expected 401 — cannot confirm the "
                "locked-down catalog posture"
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
                    "live health signing key id does not match the expected signing key id"
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
                "expected signing key id"
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
                failures.append("public trust-key issuer does not match the live URL")
            if document_alg != "Ed25519":
                failures.append("public trust-key document must use Ed25519")
            if len(active_matches) != 1 or not _matches_ed25519_public_key(
                active_matches[0] if len(active_matches) == 1 else None,
                expected_signing_public_key_sha256 or "",
            ):
                failures.append(
                    "expected signing key id is not published exactly once as an "
                    "active Ed25519 key with valid public material"
                )

    if failures:
        for item in failures:
            print(f"{BAD} {item}")
        return False

    displayed_version = body.get("version") or "unknown"
    displayed_commit_sha = body.get("commit_sha")
    displayed_sha = f", sha={displayed_commit_sha}" if displayed_commit_sha else ""
    displayed_dogfood = (
        "dogfood_tool=false"
        if dogfood_verified
        else "dogfood_tool=private (not publicly observable)"
    )
    displayed_signing_key = (
        f", signing key {expected_signing_key_id} published with the expected "
        "public-key fingerprint"
        if expected_signing_key_id is not None
        else ""
    )
    print(
        f"{OK} {base} healthy (v{displayed_version}{displayed_sha}, "
        f"proof_surfaces=false, {displayed_dogfood}, tool catalogs 401 "
        f"without credentials, no memory fallback{displayed_signing_key})"
    )
    return True


def _service_dotenv_files() -> list[Path]:
    """``.env`` files the running service could read, if any exist.

    ``get_settings()`` reads ``.env`` relative to the process working
    directory. The image runs the service from ``WORKDIR /app`` (the
    entrypoint execs uvicorn without changing directory), which is this
    script's ``REPO_ROOT`` inside the image. The current directory is checked
    as well, in case the check runs from the same place as the service.
    """
    candidates = {REPO_ROOT / ".env", Path.cwd() / ".env"}
    return sorted(path for path in candidates if path.exists())


def check_runtime_posture() -> bool:
    """Assert the dogfood posture from this process's runtime configuration.

    Meant for the deployed API container (``railway ssh``). Settings are
    built from the process environment only, never from a ``.env`` file: the
    image cannot contain one (``.dockerignore`` excludes ``.env`` and
    ``.env.*``), so inside the container this is exactly what the running
    service resolves, and a ``.env`` in some other working directory cannot
    stand in for it. If a ``.env`` file does exist where the service would
    read it, the check fails: the service's configuration could then differ
    from this process environment.

    Fails closed off Railway. A production-like ENVIRONMENT alone proves
    nothing, because every unrecognized value (``ENVIRONMENT=banana``
    included) is production-like. One of the variables Railway injects into
    a deployed service (``HOSTED_RUNTIME_MARKER_VARS`` in
    app/core/trust_mode.py) must also be present. ``railway run`` injects
    them into a local process too; that run still reads the service's
    configured variables, not the running process.

    Configuration errors are reported by type only, because a validation
    message can echo a configured value.
    """
    try:
        from app.core.config import Settings
        from app.core.trust_mode import (
            HOSTED_RUNTIME_MARKER_VARS,
            is_production_like_environment,
        )

        settings = Settings(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:
        print(
            f"{BAD} runtime posture: unable to resolve the runtime "
            f"configuration ({type(exc).__name__})"
        )
        return False

    failures: list[str] = []
    if not any(
        os.environ.get(marker, "").strip() for marker in HOSTED_RUNTIME_MARKER_VARS
    ):
        failures.append(
            "runtime posture: no Railway runtime marker "
            f"({', '.join(HOSTED_RUNTIME_MARKER_VARS)}) in this process — run "
            "--runtime-posture inside the deployed API container"
        )
    for dotenv in _service_dotenv_files():
        failures.append(
            f"runtime posture: {dotenv} exists and the service would read it "
            "— this check reads only the process environment, so it cannot "
            "vouch for that configuration; remove the file from the image"
        )
    if not is_production_like_environment(settings.ENVIRONMENT):
        failures.append(
            "runtime posture: ENVIRONMENT is not production-like in this "
            "process — run --runtime-posture inside the deployed API "
            "container, where the service's runtime configuration applies"
        )
    for flag in _DOGFOOD_RUNTIME_FLAGS:
        if getattr(settings, flag) is not False:
            failures.append(
                f"runtime posture: {flag} is enabled — the dogfood tools are "
                "local proof infrastructure and must be false in production"
            )

    if failures:
        for item in failures:
            print(f"{BAD} {item}")
        return False

    print(
        f"{OK} runtime posture: Railway runtime, production-like ENVIRONMENT, "
        + ", ".join(f"{flag}=false" for flag in _DOGFOOD_RUNTIME_FLAGS)
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
        "--runtime-posture",
        action="store_true",
        help=(
            "assert this process's runtime configuration is production-like "
            "with the dogfood tools off; run inside the deployed API container "
            "(this posture is not publicly observable)"
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
        "--expected-signing-key-id",
        default=None,
        help=(
            "signing key id --live requires to be published exactly once as an "
            "active Ed25519 key (with --expected-signing-public-key-sha256; not "
            "with --manifest)"
        ),
    )
    parser.add_argument(
        "--expected-signing-public-key-sha256",
        default=None,
        help=(
            "lowercase SHA-256 of that key's raw 32-byte public key, from the "
            "key-generation record (with --expected-signing-key-id)"
        ),
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
        "--railway-source-unbound",
        action="store_true",
        help="verify the target Railway service has no repository or image source",
    )
    parser.add_argument(
        "--railway-project",
        default="",
        help="exact Railway project id for --railway-source-unbound",
    )
    parser.add_argument(
        "--railway-environment",
        default="",
        help="exact Railway environment for --railway-source-unbound",
    )
    parser.add_argument(
        "--railway-service",
        default="",
        help="exact Railway service for --railway-source-unbound",
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
    signing_expectation_given = (
        args.expected_signing_key_id is not None
        or args.expected_signing_public_key_sha256 is not None
    )
    if args.manifest_only and (
        args.db
        or args.live
        or args.public_db
        or args.runtime_posture
        or args.railway_source_unbound
        or args.expected_version
        or args.expected_commit_sha
        or signing_expectation_given
    ):
        print(
            f"{BAD} --manifest-only cannot be combined with --db, --live, "
            "--public-db, --runtime-posture, --railway-source-unbound, or live "
            "release expectations"
        )
        return 1

    railway_target_given = any(
        (
            args.railway_project,
            args.railway_environment,
            args.railway_service,
        )
    )
    if railway_target_given and not args.railway_source_unbound:
        print(
            f"{BAD} --railway-project, --railway-environment, and "
            "--railway-service apply only to --railway-source-unbound"
        )
        return 1
    if args.railway_source_unbound and not all(
        (
            args.railway_project.strip(),
            args.railway_environment.strip(),
            args.railway_service.strip(),
        )
    ):
        print(
            f"{BAD} --railway-source-unbound requires --railway-project, "
            "--railway-environment, and --railway-service"
        )
        return 1

    # Explicit signing-key expectations stand in for a manifest's, for a live
    # gate run from another checkout. A present-but-empty value (a failed
    # substitution in a shell) is rejected rather than read as "not given".
    if signing_expectation_given:
        if args.manifest:
            print(
                f"{BAD} --expected-signing-key-id and "
                "--expected-signing-public-key-sha256 cannot be combined with "
                "--manifest, which already supplies the signing key"
            )
            return 1
        if not args.live:
            print(
                f"{BAD} --expected-signing-key-id and "
                "--expected-signing-public-key-sha256 apply only to --live"
            )
            return 1
        if (
            args.expected_signing_key_id is None
            or args.expected_signing_public_key_sha256 is None
        ):
            print(
                f"{BAD} --expected-signing-key-id and "
                "--expected-signing-public-key-sha256 must be given together"
            )
            return 1
        if _SAFE_ID_RE.fullmatch(args.expected_signing_key_id) is None:
            print(
                f"{BAD} --expected-signing-key-id must be a lowercase safe identifier"
            )
            return 1
        if _SHA256_RE.fullmatch(args.expected_signing_public_key_sha256) is None:
            print(
                f"{BAD} --expected-signing-public-key-sha256 must be a lowercase "
                "SHA-256 digest"
            )
            return 1

    # Release expectations and the manifest are inputs to the live check. An
    # explicit non-live selector on its own deselects that check, so accepting
    # them there would look like an identity check ran when it did not.
    if (
        (args.runtime_posture or args.railway_source_unbound)
        and not args.live
        and (args.expected_version or args.expected_commit_sha or args.manifest)
    ):
        print(
            f"{BAD} --expected-version, --expected-commit-sha, and --manifest "
            "apply only to --live; add --live or drop them from this run"
        )
        return 1

    # No check selected: run whatever the environment supports. The runtime
    # posture check only means something inside the deployed container, so it
    # never runs by default. --public-db configures the database check, so it
    # always runs that check: combining it with another selector must never
    # switch off the fail-closed public-URL requirement.
    selected = (
        args.db or args.live or args.runtime_posture or args.railway_source_unbound
    )
    run_db = not args.manifest_only and (args.db or args.public_db or not selected)
    run_live = not args.manifest_only and (args.live or not selected)

    results: list[bool] = []
    manifest: CustomerManifest | None = None
    effective_url = args.url.strip()
    effective_commit_sha = args.expected_commit_sha.strip()

    if args.manifest:
        try:
            manifest = _load_customer_manifest(args.manifest)
            if args.railway_source_unbound and (
                args.railway_project.strip() != manifest.railway_project_id
                or args.railway_environment.strip() != manifest.environment
            ):
                print(
                    f"{BAD} Railway source target does not match the customer manifest"
                )
                return 1
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

    if args.railway_source_unbound:
        results.append(
            check_railway_source_unbound(
                project_id=args.railway_project.strip(),
                environment=args.railway_environment.strip(),
                service=args.railway_service.strip(),
            )
        )

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

    if args.runtime_posture:
        results.append(check_runtime_posture())

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
            elif signing_expectation_given:
                live_result = check_live(
                    effective_url,
                    expected_version=args.expected_version or None,
                    expected_commit_sha=effective_commit_sha or None,
                    expected_signing_key_id=args.expected_signing_key_id,
                    expected_signing_public_key_sha256=(
                        args.expected_signing_public_key_sha256
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
            # An explicit expectation with nothing to check it against is a
            # failure even without --strict: skipping would report a release
            # identity or signing key as passed without a single request.
            unchecked = [
                flag
                for flag, value in (
                    ("--expected-version", args.expected_version),
                    ("--expected-commit-sha", args.expected_commit_sha),
                    ("--expected-signing-key-id", args.expected_signing_key_id),
                    (
                        "--expected-signing-public-key-sha256",
                        args.expected_signing_public_key_sha256,
                    ),
                )
                if value
            ]
            if unchecked:
                print(
                    f"{BAD} live posture: no PUBLIC_URL and no --url, so "
                    f"{', '.join(unchecked)} cannot be checked"
                )
                results.append(False)
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
