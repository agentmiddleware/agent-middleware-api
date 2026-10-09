"""Non-production boots that survive a failed database setup stay unready."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient


def _clear_init_failure() -> None:
    """Drop a startup failure flag when this build records one."""
    import app.db.database as database

    clearer = getattr(database, "clear_database_init_failure", None)
    if clearer is not None:
        clearer()


@pytest.fixture
async def _no_stray_startup_tasks():
    _clear_init_failure()
    before = set(asyncio.all_tasks())
    try:
        yield
    finally:
        _clear_init_failure()
        extra = [
            task
            for task in asyncio.all_tasks()
            if task not in before
            and task is not asyncio.current_task()
            and not task.done()
        ]
        for task in extra:
            task.cancel()
        if extra:
            await asyncio.gather(*extra, return_exceptions=True)


def _record_startup_logs(monkeypatch, main_module):
    recorded: list[tuple[str, str, dict]] = []
    inner = main_module.logger

    class _RecordingLogger:
        def error(self, event, *args, **kwargs):
            recorded.append(("error", event, kwargs))
            return inner.error(event, *args, **kwargs)

        def warning(self, event, *args, **kwargs):
            recorded.append(("warning", event, kwargs))
            return inner.warning(event, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(inner, name)

    monkeypatch.setattr(main_module, "logger", _RecordingLogger())
    return recorded


def _patch_startup_side_effects(monkeypatch, main_module):
    """Keep the boot path off the shared test database and off the network."""

    async def _noop_async(*_args, **_kwargs):
        return None

    async def _state_report():
        return {"ok": True, "backend": "memory", "enabled": False}

    async def _fast_sleep(delay, result=None):
        # The shutdown drain is a fixed 2 second wait. Leave every other
        # sleep (the cleanup loop) alone so this test does not spin.
        if delay == 2:
            return result
        return await asyncio.sleep(delay)

    monkeypatch.setattr(main_module.settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(main_module.settings, "TRUST_MODE_ENABLED", False)
    monkeypatch.setattr(
        main_module.settings,
        "DATABASE_URL",
        "sqlite+aiosqlite:///./test.db",
    )
    monkeypatch.setattr(main_module, "close_db", _noop_async)
    monkeypatch.setattr(main_module, "close_durable_state", _noop_async)
    monkeypatch.setattr(
        main_module, "sync_proof_surface_mcp_registration", lambda: None
    )
    monkeypatch.setattr(main_module.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(
        main_module,
        "get_durable_state",
        lambda: SimpleNamespace(health_report=_state_report),
    )

    import app.services.upstream_mcp as upstream_mcp

    monkeypatch.setattr(upstream_mcp, "register_configured_upstream_mcp", _noop_async)


@pytest.mark.asyncio
async def test_nonproduction_database_init_failure_is_loud_and_unready(
    monkeypatch, _no_stray_startup_tasks
):
    """A failed setup outside production must not look ready.

    The session database still answers SELECT 1. Readiness used to report
    that probe and ignore the failed setup, so money paths could run with
    nowhere durable to record.
    """
    import app.main as main_module

    async def _fail_init():
        raise RuntimeError("database setup failed")

    recorded = _record_startup_logs(monkeypatch, main_module)
    _patch_startup_side_effects(monkeypatch, main_module)
    monkeypatch.setattr(main_module, "init_db", _fail_init)

    async with main_module.lifespan(main_module.app):
        async with AsyncClient(
            transport=ASGITransport(app=main_module.app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health/ready")

    body = response.json()
    database = body["checks"]["database"]
    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert database["status"] == "down"
    assert database["error"] == "database_init_failed"
    assert "RuntimeError" not in response.text
    assert "database setup failed" not in response.text

    failures = [
        item for item in recorded if item[2].get("phase") == "database_init_failed"
    ]
    assert len(failures) == 1
    level, event, fields = failures[0]
    assert level == "error"
    assert event == "app_startup_failed"
    assert fields.get("continued") is True
    assert "durable" in fields.get("remediation", "")
    assert "/health/ready" in fields.get("remediation", "")


@pytest.mark.asyncio
async def test_schema_init_error_still_stops_nonproduction_boot(
    monkeypatch, _no_stray_startup_tasks
):
    """A schema error still refuses to boot, including outside production."""
    import app.main as main_module
    from app.db.database import SchemaInitError

    async def _fail_schema():
        raise SchemaInitError("required tables missing")

    _patch_startup_side_effects(monkeypatch, main_module)
    monkeypatch.setattr(main_module, "init_db", _fail_schema)

    with pytest.raises(SchemaInitError, match="required tables missing"):
        async with main_module.lifespan(main_module.app):
            pytest.fail("schema errors must stop boot")
