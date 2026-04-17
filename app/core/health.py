"""
Dependency health probes for /health/dependencies.

Each check returns a structured result so operators can tell at a glance
whether a specific external dependency is reachable. Runs in parallel
with a short per-check timeout — health endpoints must not hang on a
slow dependency.

Checks that are gated on simulation_mode return ``status="not_used"`` to
distinguish \"intentionally bypassed\" from \"broken\". Unconfigured deps
return ``status="not_configured"``. Neither counts as unhealthy.

See issue #27.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .config import get_settings
from .runtime_mode import get_simulation_modes

logger = logging.getLogger(__name__)


CHECK_TIMEOUT_SECONDS: float = 2.0

# Statuses that do not degrade the overall health verdict.
_OK_STATUSES = {"up", "not_configured", "not_used"}


async def _run_check(
    name: str,
    check: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run a dependency check, capturing latency and errors uniformly."""
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        result = {
            "status": "down",
            "error": f"timeout after {CHECK_TIMEOUT_SECONDS}s",
        }
    except Exception as exc:
        logger.debug("dependency check '%s' raised", name, exc_info=True)
        result = {"status": "down", "error": f"{type(exc).__name__}: {exc}"}

    result.setdefault("error", None)
    result["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
    return result


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


async def _check_postgres() -> dict[str, Any]:
    settings = get_settings()
    if not settings.DATABASE_URL:
        return {"status": "not_configured"}

    from ..db.database import get_engine

    engine = get_engine()
    if engine is None:
        return {"status": "not_configured"}

    async with engine.connect() as conn:
        from sqlalchemy import text

        await conn.execute(text("SELECT 1"))
    return {"status": "up"}


async def _check_redis() -> dict[str, Any]:
    settings = get_settings()
    if not settings.REDIS_URL.strip():
        return {"status": "not_configured"}

    import redis.asyncio as redis

    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        return {"status": "up"}
    finally:
        await client.aclose()


async def _check_mqtt(simulation_modes: dict[str, bool]) -> dict[str, Any]:
    # iot_bridge is the sole MQTT consumer. If it's in sim mode the broker
    # isn't actually touched — don't probe and don't fail the health check
    # just because a broker isn't up.
    if simulation_modes.get("iot_bridge", True):
        return {"status": "not_used", "reason": "iot_bridge in simulation mode"}

    settings = get_settings()
    broker_url = settings.MQTT_BROKER_URL
    if not broker_url:
        return {"status": "not_configured"}

    # Parse mqtt://host:port
    from urllib.parse import urlparse

    parsed = urlparse(broker_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 1883

    import aiomqtt

    async with aiomqtt.Client(hostname=host, port=port, timeout=CHECK_TIMEOUT_SECONDS):
        return {"status": "up", "host": host, "port": port}


async def _check_stripe() -> dict[str, Any]:
    settings = get_settings()
    if not settings.STRIPE_SECRET_KEY:
        return {"status": "not_configured"}

    import stripe

    # Stripe SDK is synchronous; run in the default executor so we don't
    # block the event loop.
    def _retrieve():
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe.Balance.retrieve()

    loop = asyncio.get_running_loop()
    balance = await loop.run_in_executor(None, _retrieve)
    mode = "live" if settings.STRIPE_SECRET_KEY.startswith("sk_live_") else "test"
    return {
        "status": "up",
        "mode": mode,
        "livemode": getattr(balance, "livemode", None),
    }


async def _check_llm(simulation_modes: dict[str, bool]) -> dict[str, Any]:
    # LLM is consumed by telemetry_pm (auto-PR) and the ai router. If
    # telemetry_pm is simulated and there's no key, don't probe.
    settings = get_settings()
    provider = settings.LLM_PROVIDER.lower().strip()

    if not settings.LLM_API_KEY and provider != "ollama":
        return {"status": "not_configured", "provider": provider}

    if simulation_modes.get("telemetry_pm", True):
        # Consumers are simulated — skip the probe to avoid needless API calls.
        return {
            "status": "not_used",
            "reason": "telemetry_pm in simulation mode",
            "provider": provider,
        }

    # Provider-specific lightweight probe.
    if provider in ("openai", "azure"):
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL or None,
        )
        models = await client.models.list()
        return {
            "status": "up",
            "provider": provider,
            "models_available": len(models.data),
        }

    if provider == "ollama":
        import httpx

        base = settings.OLLAMA_BASE_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as http:
            r = await http.get(f"{base}/api/tags")
            r.raise_for_status()
            return {"status": "up", "provider": provider}

    # Providers we know about but don't probe yet.
    return {
        "status": "not_probed",
        "provider": provider,
        "reason": "no probe implemented for this provider",
    }


# ---------------------------------------------------------------------------
# Public aggregator
# ---------------------------------------------------------------------------


async def gather_dependency_report() -> dict[str, Any]:
    """
    Run every dependency check in parallel and return a consolidated report.

    Overall status degrades to ``degraded`` if any required dependency
    returns ``down``. ``not_configured`` and ``not_used`` are both
    considered healthy.
    """
    settings = get_settings()
    sim_modes = get_simulation_modes()

    postgres, redis_res, mqtt, stripe_res, llm = await asyncio.gather(
        _run_check("postgres", _check_postgres),
        _run_check("redis", _check_redis),
        _run_check("mqtt", lambda: _check_mqtt(sim_modes)),
        _run_check("stripe", _check_stripe),
        _run_check("llm", lambda: _check_llm(sim_modes)),
    )

    dependencies = {
        "postgres": postgres,
        "redis": redis_res,
        "mqtt": mqtt,
        "stripe": stripe_res,
        "llm": llm,
    }

    unhealthy = [
        name for name, r in dependencies.items() if r.get("status") not in _OK_STATUSES
    ]
    overall = "healthy" if not unhealthy else "degraded"

    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "dependencies": dependencies,
        "simulation_modes": sim_modes,
        "unhealthy": unhealthy,
    }
