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
from .runtime_degradation import get_runtime_degradation
from ..services.signing_keys import (
    SigningKeyError,
    validate_signing_key_configuration,
)

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
    redis_url = (settings.REDIS_URL or "").strip()
    if not redis_url:
        return {"status": "not_configured"}

    import redis.asyncio as redis

    client = redis.from_url(redis_url, decode_responses=True)
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


async def _check_signing_key() -> dict[str, Any]:
    """Report signing readiness without signing, persisting, or leaking keys."""

    try:
        state = validate_signing_key_configuration()
    except SigningKeyError as exc:
        error = str(exc)
        if error not in {
            "trust_signing_private_key_required",
            "invalid_trust_signing_private_key",
        }:
            error = "signing_key_unavailable"
        return {"status": "down", "state": "invalid", "error": error}
    except Exception:
        logger.debug("signing key configuration check raised", exc_info=True)
        return {
            "status": "down",
            "state": "invalid",
            "error": "signing_key_unavailable",
        }

    if state == "ephemeral":
        return {
            "status": "up",
            "state": "ephemeral",
            "reason": "trust mode disabled; process-ephemeral signing key",
        }
    return {"status": "up", "state": "loaded"}


# ---------------------------------------------------------------------------
# Public aggregator
# ---------------------------------------------------------------------------


async def _check_sentinel(simulation_modes: dict[str, bool]) -> dict[str, Any]:
    # The human-approval gate is the sole Sentinel consumer. In sim mode the
    # service is never called — don't probe and don't degrade health over it.
    if simulation_modes.get("human_approval", True):
        return {"status": "not_used", "reason": "human_approval in simulation mode"}

    settings = get_settings()
    base_url = (settings.SENTINEL_API_URL or "").strip()
    if not base_url:
        return {"status": "not_configured"}

    import httpx

    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as http:
        resp = await http.get(f"{base_url.rstrip('/')}/health")
        resp.raise_for_status()
    return {"status": "up"}


async def gather_dependency_report() -> dict[str, Any]:
    """
    Run every dependency check in parallel and return a consolidated report.

    Overall status degrades to ``degraded`` if any required dependency
    returns ``down``. ``not_configured`` and ``not_used`` are both
    considered healthy.
    """
    settings = get_settings()
    sim_modes = get_simulation_modes()

    (
        postgres,
        redis_res,
        mqtt,
        stripe_res,
        llm,
        signing_key,
        sentinel,
    ) = await asyncio.gather(
        _run_check("postgres", _check_postgres),
        _run_check("redis", _check_redis),
        _run_check("mqtt", lambda: _check_mqtt(sim_modes)),
        _run_check("stripe", _check_stripe),
        _run_check("llm", lambda: _check_llm(sim_modes)),
        _run_check("signing_key", _check_signing_key),
        _run_check("sentinel", lambda: _check_sentinel(sim_modes)),
    )

    dependencies = {
        "postgres": postgres,
        "redis": redis_res,
        "mqtt": mqtt,
        "stripe": stripe_res,
        "llm": llm,
        "signing_key": signing_key,
        "sentinel": sentinel,
    }

    unhealthy = [
        name for name, r in dependencies.items() if r.get("status") not in _OK_STATUSES
    ]
    runtime_degradation = get_runtime_degradation()
    if runtime_degradation.get("degraded"):
        overall = "degraded"
        if "runtime_degradation" not in unhealthy:
            unhealthy = [*unhealthy, "runtime_degradation"]
    else:
        overall = "healthy" if not unhealthy else "degraded"

    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "dependencies": dependencies,
        "simulation_modes": sim_modes,
        "enable_proof_surfaces": bool(settings.ENABLE_PROOF_SURFACES),
        "enable_dogfood_tool": bool(settings.ENABLE_DOGFOOD_TOOL),
        "runtime_degradation": runtime_degradation,
        "unhealthy": unhealthy,
    }
