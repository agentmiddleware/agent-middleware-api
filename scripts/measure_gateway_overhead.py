"""Measure the gateway's own per-call overhead on the governed MCP path.

The upstream is a zero-latency in-process executor, so every millisecond
reported here is the gateway's work: key authentication, permit validation,
wallet policy, atomic budget reservation, the prepared dispatch attempt, the
one-shot dispatch claim, the charge, receipt signing, and the audit-chain
event. It is the number to subtract from an end-to-end measurement to find
what the upstream tool itself cost.

What this is not: a production SLO. It runs one ASGI worker in-process over
in-process transport (no socket), on a throwaway SQLite database.
Network, TLS, PostgreSQL round trips, and Railway's edge are all absent, so
treat the result as the floor of the hop, not its p95 in production.

The idempotency records, permit reservation, dispatch attempt, ledger, receipt,
and audit rows all live in the SQLite database, so their commits are inside the
measurement. ``STATE_BACKEND=memory`` only affects the separate key/value
state store, which the governed call path does not touch.

Usage:
    python scripts/measure_gateway_overhead.py            # 1000 calls + 1000 replays
    python scripts/measure_gateway_overhead.py --calls 200 --json out.json

Reported numbers are wall-clock per HTTP request, measured by the client.
Percentiles use nearest rank, index = round(p/100 * (n - 1)) over the sorted
samples, so with n=200 the p99 is the 3rd-largest sample and the max is a
single sample. Treat p99 and max as indicative below about 1000 samples.

The script posts to POST /mcp/messages (the legacy JSON-RPC endpoint) with a
pre-minted permit. The standard POST /mcp mints a permit per call and is
expected to cost more; it is not measured here.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import platform
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_TMP = tempfile.mkdtemp(prefix="amw-overhead-")
_BOOTSTRAP_KEY = "bench-" + secrets.token_hex(16)
os.environ.update(
    {
        "ENVIRONMENT": "local",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP}/overhead.db",
        "STATE_BACKEND": "memory",
        "ALLOW_METADATA_CREATE_ALL": "true",
        "ENABLE_PROOF_SURFACES": "false",
        "TRUST_MODE_ENABLED": "true",
        "ALLOW_LEGACY_UNPERMITTED_MCP": "false",
        "TRUST_SIGNING_PRIVATE_KEY_B64": base64.b64encode(
            secrets.token_bytes(32)
        ).decode(),
        "VALID_API_KEYS": _BOOTSTRAP_KEY,
        "RATE_LIMIT_PER_MINUTE": "1000000",
        "MCP_UPSTREAM_ENABLED": "false",
    }
)

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.database import close_db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.billing import ServiceCategory  # noqa: E402
from app.services.service_registry import get_service_registry  # noqa: E402
from app.services.upstream_mcp import UpstreamMcpResult  # noqa: E402

TOOL = "bench.upstream.echo"
# Priced low on purpose: the hourly velocity guard (VELOCITY_HOURLY_LIMIT, 1000
# credits by default) freezes a wallet that spends past it, and a benchmark that
# tripped it would be timing the denial path, not the governed call.
CREDITS_PER_CALL = 0.01
BOOTSTRAP_HEADERS = {"X-API-Key": _BOOTSTRAP_KEY}


class ZeroLatencyUpstream:
    """Behaves like the real adapter's contract, costs nothing."""

    def __init__(self) -> None:
        self.dispatches = 0

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Callable[[], Awaitable[None]],
    ) -> UpstreamMcpResult:
        del invocation_id, idempotency_key
        await before_dispatch()
        self.dispatches += 1
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"echo": arguments},
            "isError": False,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return UpstreamMcpResult(
            payload=payload,
            canonical_json=canonical,
            response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            size_bytes=len(canonical.encode()),
            is_error=False,
        )


async def _provision(
    client: AsyncClient, *, calls: int
) -> tuple[dict[str, str], str, str]:
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Overhead bench",
            "email": "bench@example.com",
            "initial_credits": calls * 10,
            "require_kyc": False,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    sponsor.raise_for_status()
    agent = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor.json()["wallet_id"],
            "agent_id": "bench-agent",
            "budget_credits": calls * 5,
            "daily_limit": calls * 5,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    agent.raise_for_status()
    wallet_id = agent.json()["wallet_id"]
    key = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "bench", "expires_in_days": 1},
        headers=BOOTSTRAP_HEADERS,
    )
    key.raise_for_status()
    permit = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key.json()["key_id"],
            "allowed_tools": [TOOL],
            "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
            "max_credits": calls * 2,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "bench-permit"},
    )
    permit.raise_for_status()
    return (
        {"X-API-Key": key.json()["api_key"]},
        wallet_id,
        permit.json()["permit_id"],
    )


def _body(*, wallet_id: str, permit_id: str, key: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": key,
        "method": "tools/call",
        "params": {
            "name": TOOL,
            # Distinct per key, otherwise the cross-key duplicate guard logs a
            # warning on every call (watch-only by default) and the run no
            # longer resembles distinct agent actions.
            "arguments": {"message": f"hello {key}"},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": key,
            },
        },
    }


def _provenance() -> dict[str, Any]:
    from importlib import metadata

    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except Exception:
            return "unknown"

    def version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "not installed"

    try:
        cpu = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        cpu = platform.processor() or "unknown"
    return {
        "git_head": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
        "load_average_1_5_15": [round(x, 2) for x in os.getloadavg()],
        "packages": {
            name: version(name)
            for name in ("sqlalchemy", "aiosqlite", "cryptography", "httpx", "mcp")
        },
    }


def _percentiles(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)

    def pct(p: float) -> float:
        index = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
        return ordered[index]

    return {
        "n": len(ordered),
        "p50_ms": round(pct(50), 2),
        "p95_ms": round(pct(95), 2),
        "p99_ms": round(pct(99), 2),
        "max_ms": round(ordered[-1], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
    }


async def _run(calls: int, warmup: int) -> dict[str, Any]:
    await init_db()
    upstream = ZeroLatencyUpstream()
    get_service_registry().register_upstream(
        service_id=TOOL,
        name="bench.echo",
        description="Zero-latency benchmark upstream",
        category=ServiceCategory.PLATFORM_FEE,
        executor=upstream,
        input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        output_schema={"type": "object"},
        credits_per_unit=CREDITS_PER_CALL,
        upstream_tool_name="bench.echo",
        upstream_origin="https://bench.invalid",
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://bench"
        ) as client:
            headers, wallet_id, permit_id = await _provision(
                client, calls=calls + warmup
            )

            async def invoke(key: str) -> tuple[float, str]:
                started = time.perf_counter()
                response = await client.post(
                    "/mcp/messages",
                    json=_body(wallet_id=wallet_id, permit_id=permit_id, key=key),
                    headers=headers,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                # JSON-RPC reports failures inside an HTTP 200, so status alone
                # proves nothing. Require a result, no error, no tool error, and
                # a receipt id; otherwise the run would time the wrong path.
                assert response.status_code == 200, (
                    f"{key}: HTTP {response.status_code}"
                )
                body = response.json()
                assert "error" not in body, f"{key}: JSON-RPC error {body.get('error')}"
                result = body.get("result") or {}
                assert result.get("isError") is False, f"{key}: tool error {result}"
                receipt_id = (result.get("receipt") or {}).get("receipt_id")
                assert receipt_id, f"{key}: no receipt id in {sorted(result)}"
                return elapsed_ms, receipt_id

            for i in range(warmup):
                await invoke(f"warm-{i}")

            first_ms: list[float] = []
            receipts: list[str] = []
            for i in range(calls):
                elapsed, receipt_id = await invoke(f"call-{i}")
                first_ms.append(elapsed)
                receipts.append(receipt_id)
            assert len(set(receipts)) == calls, (
                "first calls did not each mint a receipt"
            )

            replay_ms: list[float] = []
            for i in range(calls):
                elapsed, receipt_id = await invoke(f"call-{i}")
                assert receipt_id == receipts[i], "replay returned a different receipt"
                replay_ms.append(elapsed)
    finally:
        get_service_registry().unregister_local(TOOL)
        await close_db()

    assert upstream.dispatches == warmup + calls, (
        f"expected {warmup + calls} dispatches, saw {upstream.dispatches}"
    )
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": f"{platform.machine()} / {platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "endpoint": "POST /mcp/messages (legacy, pre-minted permit)",
        "calls": calls,
        "warmup": warmup,
        "provenance": _provenance(),
        "posture": {
            "trust_mode": "strict",
            "database": "sqlite (temp file)",
            "state_backend": "memory",
            "transport": "in-process ASGI, no network",
            "upstream_latency": "zero (in-process executor)",
        },
        "first_call": _percentiles(first_ms),
        "replay": _percentiles(replay_ms),
        "dispatches": upstream.dispatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--calls", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--json", type=Path, default=None, help="write results here")
    args = parser.parse_args()

    result = asyncio.run(_run(args.calls, args.warmup))
    print(json.dumps(result, indent=2))
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
