"""Synthetic loopback-only Redis 8.2.1 -> 8.2.9 persistence/reconnect rehearsal.

Run with the application environment and PYTHONPATH pointing at the frozen source.
This does not contact Railway or copy production data. No server is installed.
"""

import asyncio
import hashlib
import json
import logging
import os
import pathlib
import secrets
import shutil
import socket
import subprocess
import tempfile
import time

ROOT = pathlib.Path("/tmp/amw-redis-upgrade-20260909")
OUT = pathlib.Path(__file__).resolve().parent


async def main():
    import redis.asyncio as redis
    from redis.exceptions import AuthenticationError, RedisError
    from httpx import ASGITransport, AsyncClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    password = secrets.token_urlsafe(32)
    url = f"redis://:{password}@127.0.0.1:{port}/0"
    data = pathlib.Path(tempfile.mkdtemp(prefix="synthetic-", dir=ROOT))
    os.environ.update(
        ENVIRONMENT="production",
        DEBUG="false",
        STATE_BACKEND="redis",
        STATE_NAMESPACE="release_rehearsal",
        REDIS_URL=url,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.durable_state import DurableStateStore
    from app.core.rate_limiter import RateLimitMiddleware
    from app.core.runtime_degradation import get_runtime_degradation

    logging.disable(logging.CRITICAL)
    client = redis.from_url(
        url, decode_responses=False, socket_connect_timeout=1, socket_timeout=1
    )
    processes = []
    logs = []
    checks = []
    reconnect_errors = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    async def start(version, directory):
        log = open(directory / f"{version}.log", "ab")
        logs.append(log)
        proc = subprocess.Popen(
            [
                str(ROOT / f"redis-{version}" / "src/redis-server"),
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
                "--protected-mode",
                "yes",
                "--requirepass",
                password,
                "--dir",
                str(directory),
                "--dbfilename",
                "dump.rdb",
                "--save",
                "60 1",
                "--appendonly",
                "no",
            ],
            stdout=log,
            stderr=log,
        )
        processes.append(proc)
        for _ in range(100):
            assert proc.poll() is None, "Synthetic Redis exited before readiness"
            try:
                await client.ping()
                info = await client.info("server")
                check("running version " + version, info["redis_version"] == version)
                return proc
            except RedisError:
                await asyncio.sleep(0.05)
        raise AssertionError("Synthetic Redis readiness timeout")

    def stop(proc):
        proc.terminate()
        proc.wait(timeout=10)
        check("graceful Redis shutdown", proc.returncode == 0)

    calls = 0

    async def ok(_request):
        nonlocal calls
        calls += 1
        return PlainTextResponse("synthetic action reached")

    limited = RateLimitMiddleware(
        Starlette(routes=[Route("/v1/rehearsal", ok)]), requests_per_minute=1000
    )
    store = DurableStateStore()

    async def read_after_restart(key):
        # Retry only an idempotent synthetic read; never replay a tool action.
        for attempt in range(3):
            try:
                return await store.load_json(key)
            except RedisError as exc:
                reconnect_errors.append(type(exc).__name__)
                if attempt == 2:
                    raise
                await asyncio.sleep(0.1)

    http = AsyncClient(
        transport=ASGITransport(app=limited),
        base_url="http://synthetic",
        headers={"X-API-Key": "synthetic-rehearsal-caller"},
    )
    started = time.monotonic()
    try:
        old = await start("8.2.1", data)
        unauth = redis.Redis(host="127.0.0.1", port=port)
        try:
            await unauth.ping()
            raise AssertionError("Unauthenticated connection accepted")
        except AuthenticationError:
            check("unauthenticated access rejected", True)
        finally:
            await unauth.aclose()

        expected = {
            f"operation-{i:03}": {
                "operation": i,
                "receipt": "synthetic-only",
                "debit": i % 7,
            }
            for i in range(100)
        }
        for key, value in expected.items():
            await store.save_json(key, value)
        await client.set("rehearsal:ttl", "synthetic", ex=600)
        await client.hset(
            "rehearsal:hash", mapping={"counter": "42", "state": "prepared"}
        )
        await client.rpush("rehearsal:list", "a", "b", "c")
        before_response = await http.get("/v1/rehearsal")
        check("middleware permits healthy request", before_response.status_code == 200)
        await client.save()
        baseline = {k: await client.dump(k) for k in await client.keys("*")}
        await asyncio.to_thread(stop, old)
        recovery = data / "recovery"
        recovery.mkdir()
        shutil.copy2(data / "dump.rdb", recovery / "dump.rdb")
        backup_hash = hashlib.sha256((recovery / "dump.rdb").read_bytes()).hexdigest()
        before_calls = calls
        denied = await asyncio.wait_for(http.get("/v1/rehearsal"), timeout=10)
        check("Redis outage returns HTTP 503", denied.status_code == 503)
        check("outage does not reach downstream handler", calls == before_calls)
        check("production limiter uses no memory buckets", not limited._requests)
        try:
            await asyncio.wait_for(store.load_json("operation-000"), timeout=10)
            raise AssertionError("Durable read silently succeeded while Redis stopped")
        except RedisError:
            check(
                "durable state fails rather than falling back", store.backend == "redis"
            )

        patched = await start("8.2.9", data)
        for k, v in baseline.items():
            assert await client.dump(k) == v, "Synthetic RDB payload changed"
        check("all RDB payloads survived upgrade", True)
        check(
            "expiring key retained bounded TTL",
            0 < await client.ttl("rehearsal:ttl") <= 600,
        )
        for key, value in expected.items():
            assert await store.load_json(key) == value
        check("same durable-store instance reconnects", True)
        check(
            "same middleware instance reconnects",
            (await http.get("/v1/rehearsal")).status_code == 200,
        )
        sticky = get_runtime_degradation()
        check(
            "outage health marker remains latched after reconnect", sticky["degraded"]
        )
        await asyncio.to_thread(stop, patched)
        restored = await start("8.2.9", recovery)
        for key, value in expected.items():
            assert await read_after_restart(key) == value
        check("pre-upgrade synthetic RDB restores on patched Redis", True)
        await asyncio.to_thread(stop, restored)
        result = {
            "passed": True,
            "checks": checks,
            "sourceSha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "versions": ["8.2.1", "8.2.9"],
            "platform": "local macOS, source-built Redis with libc allocator",
            "syntheticRecords": len(expected),
            "persistedKeysCompared": len(baseline),
            "rdbBackupSha256": backup_hash,
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "stickyDegradationAfterReconnect": sticky,
            "transientReadErrorsOnRestoreReconnect": reconnect_errors,
            "limits": [
                "Not a Railway image/volume rehearsal",
                "No production outage or restore",
                "No throughput, RTO, RPO or zero-downtime claim",
                "Health marker reset requires a controlled process restart; no production reset performed",
            ],
        }
        (OUT / "redis-upgrade-validation.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(json.dumps(result, indent=2))
    finally:
        await http.aclose()
        await store.close()
        if limited._redis is not None:
            await limited._redis.aclose()
        await client.aclose()
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == "__main__":
    asyncio.run(main())
