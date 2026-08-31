"""Opt-in multi-process PostgreSQL proofs for governed MCP crash behavior.

The API workers and independent MCP partner run on loopback. The workers share
one explicitly isolated, disposable PostgreSQL database. This module is
intentionally skipped unless both opt-in flags are present; an opted-in run
fails closed if the database is not PostgreSQL, the application environment is
production-like, the Alembic revision is stale, or any application table
already contains data. Application proof rows are deliberately retained for
inspection, so the database must be dropped or recreated before another run.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import TextIO

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.time import utc_now
from b2a_sdk.receipt_verifier import (
    VerificationStatus,
    key_set_from_document,
    verify_bundle,
)
from tests.support.mcp_stress_preflight import (
    StressPreflightDisabled,
    StressPreflightError,
    assert_empty_database_before_migration,
    assert_expected_database,
    require_explicit_isolation,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_HEADER = "X-MCP-Stress-Control"
GOVERNED_MCP_ENDPOINT = "/mcp/invoke"
STRESS_TOOL = "stress-governed-tool"
REMOTE_STRESS_TOOL = "remote-stress-governed-tool"
_ADVISORY_LOCK_ID = int.from_bytes(b"MCPSTRES", byteorder="big", signed=False)


@dataclass(frozen=True)
class StressHarness:
    database_url: str
    run_id: str
    signing_private_key_b64: str
    signing_key_id: str
    control_token: str
    temp_root: Path


@dataclass
class StressWorker:
    process: subprocess.Popen[str]
    base_url: str
    marker_path: Path
    release_path: Path
    log_path: Path
    log_stream: TextIO


@dataclass
class RemotePartner:
    process: subprocess.Popen[str]
    base_url: str
    database_path: Path
    log_path: Path
    log_stream: TextIO
    bearer_token: str


@dataclass(frozen=True)
class SeededCall:
    wallet_id: str
    permit_id: str
    idempotency_key: str
    call_token: str
    headers: dict[str, str]
    body: dict[str, object]


@dataclass(frozen=True)
class OperationSnapshot:
    execution_count: int
    debit_count: int
    receipt_ids: tuple[str, ...]
    idempotency_record_id: str
    attempt_id: str | None
    attempt_state: str | None
    debit_refunded: bool
    idempotency_completed: bool


def _require_explicit_isolation() -> str:
    try:
        return require_explicit_isolation()
    except StressPreflightDisabled as exc:
        pytest.skip(str(exc))
    except StressPreflightError as exc:
        pytest.fail(
            str(exc),
            pytrace=False,
        )
    raise AssertionError("unreachable")


def _tree_heads() -> set[str]:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def _assert_migrated_empty_database(connection: AsyncConnection) -> None:
    try:
        await assert_expected_database(
            connection,
            os.environ["MCP_STRESS_EXPECTED_DATABASE_NAME"].strip(),
        )
        table_names = await assert_empty_database_before_migration(connection)
    except StressPreflightError as exc:
        pytest.fail(str(exc), pytrace=False)
    if "alembic_version" not in table_names:
        pytest.fail(
            "isolated PostgreSQL database is not Alembic-managed; run "
            "`alembic upgrade head` first",
            pytrace=False,
        )

    current_heads = set(
        (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalars()
    )
    expected_heads = _tree_heads()
    if current_heads != expected_heads:
        pytest.fail(
            "isolated PostgreSQL database is not at the repository migration "
            "head "
            f"(current={sorted(current_heads)}, expected={sorted(expected_heads)})",
            pytrace=False,
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_preflight_rejects_wrong_postgres_database_identity() -> None:
    _require_explicit_isolation()

    from app.db.database import get_engine

    engine = get_engine()
    assert engine is not None
    async with engine.connect() as connection:
        with pytest.raises(StressPreflightError, match="does not match"):
            await assert_expected_database(
                connection,
                f"not-the-selected-database-{uuid.uuid4().hex}",
            )


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def stress_harness(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[StressHarness]:
    database_url = _require_explicit_isolation()

    from app.db.database import get_engine

    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        pytest.fail(
            "configured database engine is not PostgreSQL",
            pytrace=False,
        )

    connection = await engine.connect()
    lock_acquired = False
    table_created = False
    try:
        lock_acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": _ADVISORY_LOCK_ID},
            )
        )
        if not lock_acquired:
            pytest.fail(
                "another MCP multiprocess stress run holds the database lock",
                pytrace=False,
            )

        await _assert_migrated_empty_database(connection)
        await connection.execute(
            text(
                """
                CREATE TABLE mcp_stress_tool_executions (
                    execution_id BIGSERIAL PRIMARY KEY,
                    call_token TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    worker_pid INTEGER NOT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                )
                """
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX ix_mcp_stress_tool_call_token "
                "ON mcp_stress_tool_executions (call_token)"
            )
        )
        await connection.commit()
        table_created = True

        run_id = f"mp-{uuid.uuid4().hex[:12]}"
        yield StressHarness(
            database_url=database_url,
            run_id=run_id,
            signing_private_key_b64=base64.b64encode(secrets.token_bytes(32)).decode(
                "ascii"
            ),
            signing_key_id=f"stress-signing-{run_id}",
            control_token=secrets.token_urlsafe(32),
            temp_root=tmp_path_factory.mktemp("mcp-postgres-multiprocess"),
        )
    finally:
        try:
            if table_created:
                await connection.execute(
                    text("DROP TABLE IF EXISTS mcp_stress_tool_executions")
                )
                await connection.commit()
        finally:
            try:
                if lock_acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": _ADVISORY_LOCK_ID},
                    )
            finally:
                await connection.close()


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _worker_output(worker: StressWorker) -> str:
    if not worker.log_stream.closed:
        worker.log_stream.flush()
    try:
        return worker.log_path.read_text(encoding="utf-8")[-12000:]
    except OSError:
        return "<worker log unavailable>"


def _stop_worker(worker: StressWorker) -> None:
    try:
        if worker.process.poll() is None:
            worker.process.terminate()
            try:
                worker.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.process.kill()
                worker.process.wait(timeout=3)
    finally:
        if not worker.log_stream.closed:
            worker.log_stream.close()


def _kill_worker(worker: StressWorker) -> None:
    """Terminate the worker without graceful shutdown or cleanup hooks."""
    try:
        if worker.process.poll() is None:
            worker.process.kill()
            worker.process.wait(timeout=3)
    finally:
        if not worker.log_stream.closed:
            worker.log_stream.close()


def _partner_output(partner: RemotePartner) -> str:
    if not partner.log_stream.closed:
        partner.log_stream.flush()
    try:
        return partner.log_path.read_text(encoding="utf-8")[-12000:]
    except OSError:
        return "<partner log unavailable>"


def _stop_partner(partner: RemotePartner) -> None:
    try:
        if partner.process.poll() is None:
            partner.process.terminate()
            try:
                partner.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                partner.process.kill()
                partner.process.wait(timeout=3)
    finally:
        if not partner.log_stream.closed:
            partner.log_stream.close()


async def _wait_for_partner(
    partner: RemotePartner,
    control_token: str,
) -> None:
    deadline = asyncio.get_running_loop().time() + 30
    headers = {CONTROL_HEADER: control_token}
    async with httpx.AsyncClient(base_url=partner.base_url, timeout=1) as client:
        while asyncio.get_running_loop().time() < deadline:
            if partner.process.poll() is not None:
                pytest.fail(
                    "remote partner exited during startup:\n"
                    + _partner_output(partner),
                    pytrace=False,
                )
            try:
                response = await client.get("/__stress/health", headers=headers)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    pytest.fail(
        "remote partner did not become ready:\n" + _partner_output(partner),
        pytrace=False,
    )


async def _start_remote_partner(harness: StressHarness) -> RemotePartner:
    port = _unused_loopback_port()
    bearer_token = secrets.token_urlsafe(32)
    database_path = harness.temp_root / "remote-partner.sqlite3"
    log_path = harness.temp_root / "remote-partner.log"
    log_stream = log_path.open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "MCP_REMOTE_PARTNER_ALLOWED_HOST": f"127.0.0.1:{port}",
            "MCP_REMOTE_PARTNER_BEARER_TOKEN": bearer_token,
            "MCP_REMOTE_PARTNER_CONTROL_TOKEN": harness.control_token,
            "MCP_REMOTE_PARTNER_DB_PATH": str(database_path),
            "MCP_REMOTE_PARTNER_HOLD_RESPONSE_DIR": str(
                harness.temp_root / "held-partner-responses"
            ),
            "PYTHONUNBUFFERED": "1",
        }
    )
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.support.mcp_remote_partner_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--lifespan",
                "on",
                "--no-access-log",
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except BaseException:
        log_stream.close()
        raise
    partner = RemotePartner(
        process=process,
        base_url=f"http://127.0.0.1:{port}",
        database_path=database_path,
        log_path=log_path,
        log_stream=log_stream,
        bearer_token=bearer_token,
    )
    try:
        await _wait_for_partner(partner, harness.control_token)
    except BaseException:
        _stop_partner(partner)
        raise
    return partner


async def _wait_for_worker(worker: StressWorker, control_token: str) -> None:
    deadline = asyncio.get_running_loop().time() + 30
    headers = {CONTROL_HEADER: control_token}
    async with httpx.AsyncClient(base_url=worker.base_url, timeout=1) as client:
        while asyncio.get_running_loop().time() < deadline:
            if worker.process.poll() is not None:
                pytest.fail(
                    "stress worker exited during startup:\n" + _worker_output(worker),
                    pytrace=False,
                )
            try:
                response = await client.get("/__stress/pid", headers=headers)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    pytest.fail(
        "stress worker did not become ready:\n" + _worker_output(worker),
        pytrace=False,
    )


async def _start_worker(
    harness: StressHarness,
    *,
    name: str,
    fault_point: str = "",
    remote_partner: RemotePartner | None = None,
) -> StressWorker:
    port = _unused_loopback_port()
    marker_path = harness.temp_root / f"{name}.marker.json"
    release_path = harness.temp_root / f"{name}.release"
    log_path = harness.temp_root / f"{name}.log"
    log_stream = log_path.open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_LEGACY_UNPERMITTED_MCP": "false",
            "ALLOW_METADATA_CREATE_ALL": "false",
            "DATABASE_URL": harness.database_url,
            "ENABLE_DOGFOOD_TOOL": "false",
            "ENABLE_PROOF_SURFACES": "false",
            "ENVIRONMENT": "test",
            "MCP_STRESS_CONTROL_TOKEN": harness.control_token,
            "MCP_STRESS_DB_ISOLATED": "1",
            "MCP_STRESS_FAULT_ACTION": "pause",
            "MCP_STRESS_FAULT_POINT": fault_point,
            "MCP_STRESS_FAULT_REPEAT": "once",
            "MCP_STRESS_MARKER_PATH": str(marker_path),
            "MCP_STRESS_RELEASE_PATH": str(release_path),
            "MCP_UPSTREAM_BEARER_TOKEN": (
                remote_partner.bearer_token if remote_partner else ""
            ),
            "MCP_UPSTREAM_CALL_TIMEOUT_SECONDS": "10",
            "MCP_UPSTREAM_CONNECT_TIMEOUT_SECONDS": "5",
            "MCP_UPSTREAM_CREDITS_PER_CALL": "2",
            "MCP_UPSTREAM_ENABLED": "true" if remote_partner else "false",
            "MCP_UPSTREAM_PUBLIC_TOOL_ID": (
                REMOTE_STRESS_TOOL if remote_partner else ""
            ),
            "MCP_UPSTREAM_TOOL_NAME": "partner.write" if remote_partner else "",
            "MCP_UPSTREAM_URL": (
                f"{remote_partner.base_url}/mcp" if remote_partner else ""
            ),
            "PUBLIC_URL": f"http://127.0.0.1:{port}",
            "PYTHONUNBUFFERED": "1",
            "REDIS_URL": "",
            "RUN_MCP_MULTIPROCESS_TESTS": "1",
            "SENTINEL_API_KEY": "",
            "SENTINEL_API_URL": "",
            "SIMULATION_MODE_HUMAN_APPROVAL": "true",
            "STATE_BACKEND": "postgres",
            "STATE_NAMESPACE": harness.run_id,
            "STRIPE_SECRET_KEY": "",
            "TRUST_MODE_ENABLED": "true",
            "TRUST_SIGNING_KEY_ID": harness.signing_key_id,
            "TRUST_SIGNING_PRIVATE_KEY_B64": harness.signing_private_key_b64,
            "VALID_API_KEYS": "test-key",
        }
    )
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.support.mcp_stress_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--lifespan",
                "on",
                "--no-access-log",
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except BaseException:
        log_stream.close()
        raise
    worker = StressWorker(
        process=process,
        base_url=f"http://127.0.0.1:{port}",
        marker_path=marker_path,
        release_path=release_path,
        log_path=log_path,
        log_stream=log_stream,
    )
    try:
        await _wait_for_worker(worker, harness.control_token)
    except BaseException:
        _stop_worker(worker)
        raise
    return worker


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def remote_partner(
    stress_harness: StressHarness,
) -> AsyncIterator[RemotePartner]:
    partner = await _start_remote_partner(stress_harness)
    try:
        yield partner
    finally:
        _stop_partner(partner)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def steady_worker(stress_harness: StressHarness) -> AsyncIterator[StressWorker]:
    worker = await _start_worker(stress_harness, name="steady")
    try:
        yield worker
    finally:
        _stop_worker(worker)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def remote_steady_worker(
    stress_harness: StressHarness,
    remote_partner: RemotePartner,
) -> AsyncIterator[StressWorker]:
    worker = await _start_worker(
        stress_harness,
        name="remote-steady",
        remote_partner=remote_partner,
    )
    try:
        yield worker
    finally:
        _stop_worker(worker)


async def _seed_call(
    harness: StressHarness,
    steady_worker: StressWorker,
    *,
    scenario: str,
    tool_name: str = STRESS_TOOL,
    requires_human_approval: bool = False,
) -> SeededCall:
    suffix = uuid.uuid4().hex[:12]
    call_token = f"{harness.run_id}-{scenario}-{suffix}"
    idempotency_key = f"invoke-{scenario}-{suffix}"
    async with httpx.AsyncClient(base_url=steady_worker.base_url, timeout=20) as client:
        provisioned = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            max_credits=20,
            idem_key=f"permit-{scenario}-{suffix}",
            requires_human_approval=requires_human_approval,
        )
    body: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": f"request-{scenario}-{suffix}",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"call_token": call_token},
            "mcpContext": {
                "wallet_id": provisioned["agent_wallet_id"],
                "permit_id": permit["permit_id"],
                "idempotency_key": idempotency_key,
            },
        },
    }
    return SeededCall(
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key=idempotency_key,
        call_token=call_token,
        headers=provisioned["agent_headers"],
        body=body,
    )


async def _invoke(worker: StressWorker, seeded: SeededCall) -> httpx.Response:
    async with httpx.AsyncClient(base_url=worker.base_url, timeout=30) as client:
        return await client.post(
            "/mcp/messages",
            json=seeded.body,
            headers=seeded.headers,
        )


async def _wait_for_marker(worker: StressWorker) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        if worker.process.poll() is not None:
            pytest.fail(
                "fault worker exited before writing its marker:\n"
                + _worker_output(worker),
                pytrace=False,
            )
        try:
            return json.loads(worker.marker_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            await asyncio.sleep(0.02)
    pytest.fail(
        "fault marker was not written:\n" + _worker_output(worker),
        pytrace=False,
    )


def _release_worker(worker: StressWorker) -> None:
    worker.release_path.write_text("release\n", encoding="utf-8")


def _assert_in_progress(response: httpx.Response) -> None:
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["message"] == "idempotency_in_progress"


async def _reconcile(
    harness: StressHarness,
    worker: StressWorker,
    *,
    idle_seconds: int = 0,
) -> dict[str, object]:
    async with httpx.AsyncClient(base_url=worker.base_url, timeout=20) as client:
        response = await client.post(
            "/__stress/reconcile",
            params={"idle_seconds": idle_seconds},
            headers={CONTROL_HEADER: harness.control_token},
        )
    assert response.status_code == 200
    return response.json()


async def _age_idempotency_record(
    seeded: SeededCall,
    *,
    seconds: int,
) -> None:
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE idempotency_records SET created_at = :created_at "
                "WHERE wallet_id = :wallet_id "
                "AND endpoint = :endpoint "
                "AND idempotency_key = :idempotency_key"
            ),
            {
                "created_at": utc_now() - timedelta(seconds=seconds),
                "wallet_id": seeded.wallet_id,
                "endpoint": GOVERNED_MCP_ENDPOINT,
                "idempotency_key": seeded.idempotency_key,
            },
        )
        await session.commit()


async def _snapshot(seeded: SeededCall) -> OperationSnapshot:
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        record_row = (
            await session.execute(
                text(
                    """
                    SELECT record_id, response_json
                    FROM idempotency_records
                    WHERE wallet_id = :wallet_id
                      AND endpoint = :endpoint
                      AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "wallet_id": seeded.wallet_id,
                    "endpoint": GOVERNED_MCP_ENDPOINT,
                    "idempotency_key": seeded.idempotency_key,
                },
            )
        ).one()
        record_id = str(record_row.record_id)
        execution_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM mcp_stress_tool_executions "
                        "WHERE call_token = :call_token"
                    ),
                    {"call_token": seeded.call_token},
                )
            ).scalar_one()
        )
        debit_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM ledger_entries "
                        "WHERE operation_key = :record_id AND action = 'debit'"
                    ),
                    {"record_id": record_id},
                )
            ).scalar_one()
        )
        receipt_ids = tuple(
            (
                await session.execute(
                    text(
                        "SELECT receipt_id FROM receipts "
                        "WHERE idempotency_record_id = :record_id "
                        "ORDER BY receipt_id"
                    ),
                    {"record_id": record_id},
                )
            ).scalars()
        )
        attempt_row = (
            await session.execute(
                text(
                    """
                    SELECT attempt_id, state, debit_refunded_at
                    FROM mcp_dispatch_attempts
                    WHERE idempotency_record_id = :record_id
                    """
                ),
                {"record_id": record_id},
            )
        ).one_or_none()
    return OperationSnapshot(
        execution_count=execution_count,
        debit_count=debit_count,
        receipt_ids=receipt_ids,
        idempotency_record_id=record_id,
        attempt_id=(str(attempt_row.attempt_id) if attempt_row is not None else None),
        attempt_state=(str(attempt_row.state) if attempt_row is not None else None),
        debit_refunded=(
            attempt_row is not None and attempt_row.debit_refunded_at is not None
        ),
        idempotency_completed=record_row.response_json is not None,
    )


async def _permit_spent_credits(seeded: SeededCall) -> Decimal:
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        value = (
            await session.execute(
                text("SELECT spent_credits FROM permits WHERE permit_id = :permit_id"),
                {"permit_id": seeded.permit_id},
            )
        ).scalar_one()
    return Decimal(str(value))


async def _partner_executions(
    harness: StressHarness,
    partner: RemotePartner,
    call_token: str,
) -> list[dict[str, object]]:
    async with httpx.AsyncClient(base_url=partner.base_url, timeout=5) as client:
        response = await client.get(
            "/__stress/executions",
            params={"call_token": call_token},
            headers={CONTROL_HEADER: harness.control_token},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == len(payload["executions"])
    return payload["executions"]


async def _approval_status(seeded: SeededCall) -> str:
    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        status_value = await session.scalar(
            text(
                """
                SELECT status
                FROM human_approvals
                WHERE wallet_id = :wallet_id
                  AND permit_id = :permit_id
                  AND idempotency_key = :idempotency_key
                """
            ),
            {
                "wallet_id": seeded.wallet_id,
                "permit_id": seeded.permit_id,
                "idempotency_key": seeded.idempotency_key,
            },
        )
    assert status_value is not None
    return str(status_value)


def _assert_delivery_uncertain(response: httpx.Response) -> dict[str, object]:
    assert response.status_code == 200
    error = response.json()["error"]
    assert error["code"] == -32005
    assert error["message"] == "delivery_uncertain"
    receipt = error["data"]["receipt"]
    assert receipt["outcome"] == "delivery_uncertain"
    return receipt


@pytest.mark.asyncio(loop_scope="session")
async def test_two_processes_serialize_one_governed_side_effect(
    stress_harness: StressHarness,
    steady_worker: StressWorker,
) -> None:
    async with httpx.AsyncClient(base_url=steady_worker.base_url, timeout=5) as client:
        missing = await client.get("/__stress/pid")
        wrong = await client.get(
            "/__stress/pid",
            headers={CONTROL_HEADER: "wrong-control-token"},
        )
        missing_reconcile = await client.post("/__stress/reconcile")
        wrong_reconcile = await client.post(
            "/__stress/reconcile",
            headers={CONTROL_HEADER: "wrong-control-token"},
        )
    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert missing_reconcile.status_code == 403
    assert wrong_reconcile.status_code == 403

    seeded = await _seed_call(stress_harness, steady_worker, scenario="overlap")
    fault_worker = await _start_worker(
        stress_harness,
        name=f"overlap-{uuid.uuid4().hex[:8]}",
        fault_point="after_tool_side_effect",
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_tool_side_effect"

        competing = await _invoke(steady_worker, seeded)
        _assert_in_progress(competing)

        _release_worker(fault_worker)
        first = await asyncio.wait_for(first_task, timeout=20)
        assert first.status_code == 200
        assert "result" in first.json()

        replay = await _invoke(steady_worker, seeded)
        assert replay.status_code == 200
        assert replay.json()["result"] == first.json()["result"]

        snapshot = await _snapshot(seeded)
        assert snapshot.execution_count == 1
        assert snapshot.debit_count == 1
        assert len(snapshot.receipt_ids) == 1
        assert (
            first.json()["result"]["receipt"]["receipt_id"] == snapshot.receipt_ids[0]
        )
    finally:
        _release_worker(fault_worker)
        _stop_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_receipt_commit_survives_worker_death_and_reconciles(
    stress_harness: StressHarness,
    steady_worker: StressWorker,
) -> None:
    seeded = await _seed_call(stress_harness, steady_worker, scenario="receipt-crash")
    fault_worker = await _start_worker(
        stress_harness,
        name=f"receipt-crash-{uuid.uuid4().hex[:8]}",
        fault_point="after_receipt_commit",
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_receipt_commit"
        receipt_id = str(marker["context"]["receipt_id"])  # type: ignore[index]

        _stop_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        blocked = await _invoke(steady_worker, seeded)
        _assert_in_progress(blocked)

        reconciliation = await _reconcile(stress_harness, steady_worker)
        assert reconciliation["idempotency_repaired"] == 1
        assert reconciliation["idempotency_needs_review"] == 0

        replay = await _invoke(steady_worker, seeded)
        assert replay.status_code == 200
        result = replay.json()["result"]
        assert result["reconciled"] is True
        assert result["outcome"] == "success"
        assert result["isError"] is False
        assert result["receipt_id"] == receipt_id

        snapshot = await _snapshot(seeded)
        assert snapshot.execution_count == 1
        assert snapshot.debit_count == 1
        assert snapshot.receipt_ids == (receipt_id,)
    finally:
        _stop_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_post_side_effect_crash_requires_review_without_redispatch(
    stress_harness: StressHarness,
    steady_worker: StressWorker,
) -> None:
    seeded = await _seed_call(stress_harness, steady_worker, scenario="manual-review")
    fault_worker = await _start_worker(
        stress_harness,
        name=f"manual-review-{uuid.uuid4().hex[:8]}",
        fault_point="after_tool_side_effect",
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_tool_side_effect"

        _stop_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        blocked = await _invoke(steady_worker, seeded)
        _assert_in_progress(blocked)
        before = await _snapshot(seeded)
        assert before.execution_count == 1
        assert before.debit_count == 1
        assert before.receipt_ids == ()

        reconciliation = await _reconcile(stress_harness, steady_worker)
        assert reconciliation["idempotency_repaired"] == 0
        assert reconciliation["idempotency_needs_review"] == 1

        replay = await _invoke(steady_worker, seeded)
        _assert_in_progress(replay)
        after = await _snapshot(seeded)
        assert after == before
    finally:
        _stop_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_remote_approval_crash_before_prepare_retries_without_losing_authority(
    stress_harness: StressHarness,
    remote_partner: RemotePartner,
    remote_steady_worker: StressWorker,
) -> None:
    seeded = await _seed_call(
        stress_harness,
        remote_steady_worker,
        scenario="remote-approval-crash",
        tool_name=REMOTE_STRESS_TOOL,
        requires_human_approval=True,
    )
    fault_worker = await _start_worker(
        stress_harness,
        name=f"remote-approval-crash-{uuid.uuid4().hex[:8]}",
        fault_point="after_approval_before_prepare",
        remote_partner=remote_partner,
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_approval_before_prepare"

        before = await _snapshot(seeded)
        assert before.execution_count == 0
        assert before.debit_count == 0
        assert before.receipt_ids == ()
        assert before.attempt_id is None
        assert before.idempotency_completed is False
        assert await _permit_spent_credits(seeded) == Decimal("0")
        assert await _approval_status(seeded) == "approved"
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == []
        )

        _kill_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        blocked = await _invoke(remote_steady_worker, seeded)
        _assert_in_progress(blocked)
        await _age_idempotency_record(seeded, seconds=301)
        reconciliation = await _reconcile(
            stress_harness,
            remote_steady_worker,
            idle_seconds=300,
        )
        assert reconciliation["dispatch_uncertain"] == 0
        assert reconciliation["idempotency_repaired"] == 1
        assert await _approval_status(seeded) == "approved"
        assert await _permit_spent_credits(seeded) == Decimal("0")

        replay = await _invoke(remote_steady_worker, seeded)
        assert replay.status_code == 200
        result = replay.json()["result"]
        assert result["receipt"]["outcome"] == "success"
        after = await _snapshot(seeded)
        assert after.debit_count == 1
        assert after.attempt_state == "succeeded"
        assert after.debit_refunded is False
        assert after.idempotency_completed is True
        assert after.receipt_ids == (result["receipt"]["receipt_id"],)
        assert await _permit_spent_credits(seeded) > Decimal("0")
        assert await _approval_status(seeded) == "consumed"
        executions = await _partner_executions(
            stress_harness, remote_partner, seeded.call_token
        )
        assert len(executions) == 1
        assert executions[0]["invocation_id"] == after.idempotency_record_id
        assert executions[0]["idempotency_key"] == seeded.idempotency_key
    finally:
        _kill_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_remote_approval_prepare_transaction_rolls_back_on_process_kill(
    stress_harness: StressHarness,
    remote_partner: RemotePartner,
    remote_steady_worker: StressWorker,
) -> None:
    seeded = await _seed_call(
        stress_harness,
        remote_steady_worker,
        scenario="remote-approval-transaction-kill",
        tool_name=REMOTE_STRESS_TOOL,
        requires_human_approval=True,
    )
    fault_worker = await _start_worker(
        stress_harness,
        name=f"remote-approval-tx-kill-{uuid.uuid4().hex[:8]}",
        fault_point="after_approval_budget_attempt_flush_before_commit",
        remote_partner=remote_partner,
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_approval_budget_attempt_flush_before_commit"
        assert marker["context"]["approval_id"] is not None
        assert marker["context"]["attempt_id"] is not None

        # All three writes have been flushed, but PostgreSQL readers see the
        # last committed versions while the worker is paused: neither
        # authorization, budget, nor attempt has escaped the transaction.
        before = await _snapshot(seeded)
        assert before.execution_count == 0
        assert before.debit_count == 0
        assert before.receipt_ids == ()
        assert before.attempt_id is None
        assert before.idempotency_completed is False
        assert await _permit_spent_credits(seeded) == Decimal("0")
        assert await _approval_status(seeded) == "approved"
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == []
        )

        _kill_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        blocked = await _invoke(remote_steady_worker, seeded)
        _assert_in_progress(blocked)
        await _age_idempotency_record(seeded, seconds=301)
        reconciliation = await _reconcile(
            stress_harness,
            remote_steady_worker,
            idle_seconds=300,
        )
        assert reconciliation["dispatch_uncertain"] == 0
        assert reconciliation["idempotency_repaired"] == 1
        assert await _approval_status(seeded) == "approved"
        assert await _permit_spent_credits(seeded) == Decimal("0")

        replay = await _invoke(remote_steady_worker, seeded)
        assert replay.status_code == 200
        result = replay.json()["result"]
        receipt = result["receipt"]
        assert receipt["outcome"] == "success"
        after = await _snapshot(seeded)
        assert after.debit_count == 1
        assert after.attempt_id is not None
        assert after.attempt_state == "succeeded"
        assert after.debit_refunded is False
        assert after.idempotency_completed is True
        assert after.receipt_ids == (receipt["receipt_id"],)
        assert await _permit_spent_credits(seeded) == Decimal(
            receipt["credits_authorized"]
        )
        assert await _approval_status(seeded) == "consumed"
        executions = await _partner_executions(
            stress_harness,
            remote_partner,
            seeded.call_token,
        )
        assert len(executions) == 1
        assert executions[0]["invocation_id"] == after.idempotency_record_id
        assert executions[0]["idempotency_key"] == seeded.idempotency_key
    finally:
        _kill_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_remote_claim_commit_before_send_crash_never_redispatches(
    stress_harness: StressHarness,
    remote_partner: RemotePartner,
    remote_steady_worker: StressWorker,
) -> None:
    seeded = await _seed_call(
        stress_harness,
        remote_steady_worker,
        scenario="remote-claim-crash",
        tool_name=REMOTE_STRESS_TOOL,
    )
    fault_worker = await _start_worker(
        stress_harness,
        name=f"remote-claim-crash-{uuid.uuid4().hex[:8]}",
        fault_point="after_dispatch_claim",
        remote_partner=remote_partner,
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_dispatch_claim"

        before = await _snapshot(seeded)
        assert before.execution_count == 0
        assert before.debit_count == 1
        assert before.receipt_ids == ()
        assert before.attempt_state == "dispatch_claimed"
        assert before.debit_refunded is False
        assert before.idempotency_completed is False
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == []
        )

        _kill_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        blocked = await _invoke(remote_steady_worker, seeded)
        _assert_in_progress(blocked)
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == []
        )

        reconciliation = await _reconcile(stress_harness, remote_steady_worker)
        assert reconciliation["dispatch_uncertain"] == 1
        assert reconciliation["dispatch_failed_attempt_ids"] == []

        replay = await _invoke(remote_steady_worker, seeded)
        receipt = _assert_delivery_uncertain(replay)
        after = await _snapshot(seeded)
        assert after.execution_count == 0
        assert after.debit_count == 1
        assert after.attempt_state == "delivery_uncertain"
        assert after.debit_refunded is False
        assert after.idempotency_completed is True
        assert after.receipt_ids == (receipt["receipt_id"],)
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == []
        )
    finally:
        _kill_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_remote_ack_before_terminal_commit_crash_becomes_uncertain_without_redispatch(
    stress_harness: StressHarness,
    remote_partner: RemotePartner,
    remote_steady_worker: StressWorker,
) -> None:
    seeded = await _seed_call(
        stress_harness,
        remote_steady_worker,
        scenario="remote-ack-crash",
        tool_name=REMOTE_STRESS_TOOL,
    )
    fault_worker = await _start_worker(
        stress_harness,
        name=f"remote-ack-crash-{uuid.uuid4().hex[:8]}",
        fault_point="after_upstream_ack_before_terminal",
        remote_partner=remote_partner,
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    try:
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "after_upstream_ack_before_terminal"

        before = await _snapshot(seeded)
        executions = await _partner_executions(
            stress_harness, remote_partner, seeded.call_token
        )
        assert len(executions) == 1
        execution = executions[0]
        assert execution["invocation_id"] == before.idempotency_record_id
        assert execution["idempotency_key"] == seeded.idempotency_key
        assert execution["worker_pid"] != marker["pid"]
        assert before.execution_count == 0
        assert before.debit_count == 1
        assert before.receipt_ids == ()
        assert before.attempt_state == "dispatch_claimed"
        assert before.debit_refunded is False
        assert before.idempotency_completed is False

        _kill_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        blocked = await _invoke(remote_steady_worker, seeded)
        _assert_in_progress(blocked)
        assert (
            len(
                await _partner_executions(
                    stress_harness, remote_partner, seeded.call_token
                )
            )
            == 1
        )

        reconciliation = await _reconcile(stress_harness, remote_steady_worker)
        assert reconciliation["dispatch_uncertain"] == 1
        assert reconciliation["dispatch_failed_attempt_ids"] == []

        replay = await _invoke(remote_steady_worker, seeded)
        receipt = _assert_delivery_uncertain(replay)
        after = await _snapshot(seeded)
        assert after.execution_count == 0
        assert after.debit_count == 1
        assert after.attempt_state == "delivery_uncertain"
        assert after.debit_refunded is False
        assert after.idempotency_completed is True
        assert after.receipt_ids == (receipt["receipt_id"],)
        assert (
            len(
                await _partner_executions(
                    stress_harness, remote_partner, seeded.call_token
                )
            )
            == 1
        )
    finally:
        _kill_worker(fault_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_remote_response_loss_recovers_charged_receipt_verified_offline(
    stress_harness: StressHarness,
    remote_partner: RemotePartner,
    remote_steady_worker: StressWorker,
) -> None:
    """Join synthetic effect/response-loss recovery; not partner validation."""
    from app.db.database import get_session_factory

    seeded = await _seed_call(
        stress_harness,
        remote_steady_worker,
        scenario="remote-response-loss",
        tool_name=REMOTE_STRESS_TOOL,
    )
    fault_worker = await _start_worker(
        stress_harness,
        name=f"remote-response-loss-{uuid.uuid4().hex[:8]}",
        fault_point="before_receipt_commit",
        remote_partner=remote_partner,
    )
    hold_path = (
        stress_harness.temp_root
        / "held-partner-responses"
        / hashlib.sha256(seeded.call_token.encode("utf-8")).hexdigest()
    )
    first_task: asyncio.Task[httpx.Response] | None = None
    replay_worker: StressWorker | None = None
    factory = get_session_factory()
    expected_request_hash = hashlib.sha256(
        json.dumps(
            {
                "tool_name": REMOTE_STRESS_TOOL,
                "arguments": {"call_token": seeded.call_token},
                "wallet_id": seeded.wallet_id,
                "permit_id": seeded.permit_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    async def assert_charged_accounting(record_id: str) -> str:
        async with factory() as session:
            debit = (
                await session.execute(
                    text(
                        "SELECT entry_id, operation_key, amount FROM ledger_entries "
                        "WHERE wallet_id = :wallet_id AND action = 'debit'"
                    ),
                    {"wallet_id": seeded.wallet_id},
                )
            ).one()
            refunds = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM ledger_entries "
                    "WHERE wallet_id = :wallet_id AND action = 'refund'"
                ),
                {"wallet_id": seeded.wallet_id},
            )
            balance = await session.scalar(
                text("SELECT balance FROM wallets WHERE wallet_id = :wallet_id"),
                {"wallet_id": seeded.wallet_id},
            )
        assert debit.operation_key == record_id
        assert Decimal(str(debit.amount)) == Decimal("-2")
        assert refunds == 0
        assert Decimal(str(initial_balance)) - Decimal(str(balance)) == Decimal("2")
        assert await _permit_spent_credits(seeded) == Decimal("2")
        return str(debit.entry_id)

    try:
        async with factory() as session:
            initial_balance = await session.scalar(
                text("SELECT balance FROM wallets WHERE wallet_id = :wallet_id"),
                {"wallet_id": seeded.wallet_id},
            )
        assert initial_balance is not None
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == []
        )
        hold_path.parent.mkdir(parents=True, exist_ok=True)
        hold_path.write_text("hold this token's response\n", encoding="utf-8")
        first_task = asyncio.create_task(_invoke(fault_worker, seeded))
        marker = await _wait_for_marker(fault_worker)
        assert marker["point"] == "before_receipt_commit"
        assert hold_path.exists()

        # The real upstream deadline expired while the independently committed
        # effect remained visible. Kill before receipt persistence, not before
        # the gateway has classified the missing response.
        before = await _snapshot(seeded)
        executions = await _partner_executions(
            stress_harness, remote_partner, seeded.call_token
        )
        assert len(executions) == 1
        execution = executions[0]
        assert execution["call_token"] == seeded.call_token
        assert execution["invocation_id"] == before.idempotency_record_id
        assert execution["idempotency_key"] == seeded.idempotency_key
        assert execution["worker_pid"] != marker["pid"]
        assert before.execution_count == 0
        assert before.debit_count == 1
        assert before.attempt_state == "delivery_uncertain"
        assert before.receipt_ids == ()
        assert before.debit_refunded is False
        assert before.idempotency_completed is False
        debit_id = await assert_charged_accounting(before.idempotency_record_id)
        async with factory() as session:
            terminal = (
                await session.execute(
                    text(
                        "SELECT d.request_hash, d.result_json, d.completed_at, "
                        "d.dispatch_claim_hash, d.dispatched_at, d.ledger_entry_id, "
                        "d.credits_authorized, d.credits_charged, "
                        "i.request_hash AS identity_request_hash, i.idempotency_key "
                        "FROM mcp_dispatch_attempts d "
                        "JOIN idempotency_records i "
                        "ON i.record_id = d.idempotency_record_id "
                        "WHERE d.attempt_id = :attempt_id"
                    ),
                    {"attempt_id": before.attempt_id},
                )
            ).one()
        assert json.loads(terminal.result_json) == {"error": "delivery_uncertain"}
        assert terminal.completed_at is not None
        assert terminal.dispatch_claim_hash is not None
        assert terminal.dispatched_at is not None
        assert terminal.ledger_entry_id == debit_id
        assert terminal.request_hash == expected_request_hash
        assert terminal.identity_request_hash == expected_request_hash
        assert terminal.idempotency_key == execution["idempotency_key"]
        assert Decimal(str(terminal.credits_authorized)) == Decimal("2")
        assert Decimal(str(terminal.credits_charged)) == Decimal("2")

        _kill_worker(fault_worker)
        await asyncio.gather(first_task, return_exceptions=True)

        # Reuse the complete original body on another gateway process.
        blocked = await _invoke(remote_steady_worker, seeded)
        _assert_in_progress(blocked)
        assert await _snapshot(seeded) == before
        reconciliation = await _reconcile(stress_harness, remote_steady_worker)
        assert reconciliation["dispatch_terminal_recovered"] == 1
        assert reconciliation["dispatch_failed_attempt_ids"] == []

        replay = await _invoke(remote_steady_worker, seeded)
        receipt = _assert_delivery_uncertain(replay)
        assert Decimal(str(receipt["credits_charged"])) == Decimal("2")
        after = await _snapshot(seeded)
        assert after.attempt_id == before.attempt_id
        assert after.attempt_state == "delivery_uncertain"
        assert after.debit_count == 1
        assert after.debit_refunded is False
        assert after.idempotency_completed is True
        assert after.receipt_ids == (receipt["receipt_id"],)
        assert await assert_charged_accounting(after.idempotency_record_id) == debit_id
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == executions
        )

        async with httpx.AsyncClient(
            base_url=remote_steady_worker.base_url, timeout=10
        ) as client:
            portable_response = await client.get(
                f"/v1/receipts/{receipt['receipt_id']}/portable",
                headers=seeded.headers,
            )
            keys_response = await client.get("/.well-known/trust-keys.json")
        assert portable_response.status_code == 200, portable_response.text
        assert keys_response.status_code == 200, keys_response.text
        portable = portable_response.json()
        keys = key_set_from_document(keys_response.json())
        trusted_key = (
            Ed25519PrivateKey.from_private_bytes(
                base64.b64decode(stress_harness.signing_private_key_b64)
            )
            .public_key()
            .public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
        assert keys[stress_harness.signing_key_id] == trusted_key
        trusted_keys = {stress_harness.signing_key_id: trusted_key}

        # Verification is offline. The expected issuer checks an unsigned
        # export envelope; the independently pinned key authenticates claims.
        verified = verify_bundle(
            portable,
            trusted_keys,
            expected_issuer=remote_steady_worker.base_url,
        )
        assert verified.status is VerificationStatus.VERIFIED, verified.reason
        assert verified.key_id == stress_harness.signing_key_id
        assert verified.receipt_id == receipt["receipt_id"]
        assert verified.claims["outcome"] == "delivery_uncertain"
        assert verified.claims["tool"] == REMOTE_STRESS_TOOL
        assert verified.claims["wallet_id"] == seeded.wallet_id
        assert verified.claims["permit_id"] == seeded.permit_id
        assert verified.claims["idempotency_record_id"] == execution["invocation_id"]
        assert verified.claims["dispatch_attempt_id"] == after.attempt_id
        assert verified.claims["ledger_entry_id"] == debit_id
        assert verified.claims["request_hash"] == expected_request_hash
        assert Decimal(verified.claims["credits_authorized"]) == Decimal("2")
        assert Decimal(verified.claims["credits_charged"]) == Decimal("2")
        wrong_issuer = verify_bundle(
            portable, trusted_keys, expected_issuer=fault_worker.base_url
        )
        assert wrong_issuer.status is VerificationStatus.MISMATCH
        wrong_keys = {
            stress_harness.signing_key_id: bytes(value ^ 1 for value in trusted_key)
        }
        wrong_key_result = verify_bundle(portable, wrong_keys)
        assert wrong_key_result.status is VerificationStatus.INVALID
        tampered = dict(portable)
        forged_claims = json.loads(portable["signing_input"])
        forged_claims["credits_charged"] = "0"
        tampered["signing_input"] = json.dumps(
            forged_claims, sort_keys=True, separators=(",", ":")
        )
        tampered_result = verify_bundle(tampered, trusted_keys)
        assert tampered_result.status is VerificationStatus.INVALID

        repeated = await _reconcile(stress_harness, remote_steady_worker)
        assert repeated["dispatch_terminal_recovered"] == 0
        assert repeated["dispatch_failed_attempt_ids"] == []
        replay_worker = await _start_worker(
            stress_harness,
            name=f"remote-response-loss-replay-{uuid.uuid4().hex[:8]}",
            remote_partner=remote_partner,
        )
        assert replay_worker.process.pid != remote_steady_worker.process.pid
        assert replay_worker.process.pid != marker["pid"]
        second_replay = await _invoke(replay_worker, seeded)
        second_receipt = _assert_delivery_uncertain(second_replay)
        assert second_receipt["receipt_id"] == receipt["receipt_id"]
        assert second_receipt["signature"] == receipt["signature"]
        assert second_receipt == receipt
        assert second_replay.json()["error"] == replay.json()["error"]
        assert await _snapshot(seeded) == after
        assert await assert_charged_accounting(after.idempotency_record_id) == debit_id
        assert (
            await _partner_executions(stress_harness, remote_partner, seeded.call_token)
            == executions
        )
    finally:
        _kill_worker(fault_worker)
        hold_path.unlink(missing_ok=True)
        if replay_worker is not None:
            _stop_worker(replay_worker)
        if first_task is not None:
            await asyncio.gather(first_task, return_exceptions=True)
