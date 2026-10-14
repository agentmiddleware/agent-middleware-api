"""Backlog #8: retry-loop alert on the FIRST new-key repeat of the same call."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import update as sa_update

from app.core.config import get_settings
from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel
from app.schemas.billing import ServiceCategory
from app.services import idempotency as idempotency_module
from app.services.idempotency import (
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.service_registry import get_service_registry
from tests.test_mcp_trust_mode import (
    _jsonrpc_body,
    client,  # noqa: F401 - fixture
    strict_trust_mode,  # noqa: F401 - fixture
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

ALERT = "retry_loop_first_repeat"
LOGGER = "app.services.idempotency"
ENDPOINT = "mcp:governed-test"


@pytest.fixture
def alert_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RETRY_LOOP_ALERT_ENABLED", True)
    monkeypatch.setattr(settings, "RETRY_LOOP_ALERT_WINDOW_SECONDS", 600)


def _alerts(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.message == ALERT]


async def _begin(wallet_id: str, key: str, payload: dict) -> str:
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=wallet_id,
        endpoint=ENDPOINT,
        idempotency_key=key,
        request_payload=payload,
    )
    return begun.record_id


@pytest.mark.anyio
async def test_alert_is_off_by_default(
    client,  # noqa: F811
    clean_database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert get_settings().RETRY_LOOP_ALERT_ENABLED is False
    wallet_id = (await provision_agent_wallet(client))["agent_wallet_id"]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for i in range(3):
            await _begin(wallet_id, f"off-{i}", {"tool": "t", "arguments": {"a": 1}})
    assert _alerts(caplog) == []


@pytest.mark.anyio
async def test_alert_fires_once_on_first_new_key_repeat_only(
    client,  # noqa: F811
    clean_database,
    alert_on,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    payload = {"tool": "t", "arguments": {"a": 1}}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        first = await _begin(wallet_id, "k-1", payload)
        assert _alerts(caplog) == []

        second = await _begin(wallet_id, "k-2", payload)
        alerts = _alerts(caplog)
        assert len(alerts) == 1
        assert alerts[0].prior_record_id == first  # type: ignore[attr-defined]
        assert alerts[0].record_id == second  # type: ignore[attr-defined]
        assert alerts[0].wallet_id == wallet_id  # type: ignore[attr-defined]

        # Further repeats in the same window do not re-alert.
        await _begin(wallet_id, "k-3", payload)
        # Same-key retry is a replay (here: still in progress), not a repeat.
        with pytest.raises(IdempotencyInProgressError):
            await _begin(wallet_id, "k-2", payload)
        # Different arguments are a different call.
        await _begin(wallet_id, "k-4", {"tool": "t", "arguments": {"a": 2}})
        assert len(_alerts(caplog)) == 1


@pytest.mark.anyio
async def test_alert_is_scoped_per_caller(
    client,  # noqa: F811
    clean_database,
    alert_on,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wallet_a = (await provision_agent_wallet(client))["agent_wallet_id"]
    wallet_b = (await provision_agent_wallet(client))["agent_wallet_id"]
    payload = {"tool": "t", "arguments": {"a": 1}}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await _begin(wallet_a, "k-1", payload)
        await _begin(wallet_b, "k-1", payload)
    assert _alerts(caplog) == []


@pytest.mark.anyio
async def test_alert_window_is_sliding(
    client,  # noqa: F811
    clean_database,
    alert_on,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wallet_id = (await provision_agent_wallet(client))["agent_wallet_id"]
    payload = {"tool": "t", "arguments": {"a": 1}}
    old = await _begin(wallet_id, "k-old", payload)
    async with get_session_factory()() as session:
        await session.execute(
            sa_update(IdempotencyRecordModel)
            .where(IdempotencyRecordModel.record_id == old)
            .values(created_at=utc_now() - timedelta(seconds=601))
        )
        await session.commit()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await _begin(wallet_id, "k-new-1", payload)  # only one inside window
        assert _alerts(caplog) == []
        await _begin(wallet_id, "k-new-2", payload)  # first repeat inside window
        assert len(_alerts(caplog)) == 1


@pytest.mark.anyio
async def test_alert_failure_never_blocks_the_call(
    client,  # noqa: F811
    clean_database,
    alert_on,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wallet_id = (await provision_agent_wallet(client))["agent_wallet_id"]
    payload = {"tool": "t", "arguments": {"a": 1}}
    await _begin(wallet_id, "k-1", payload)

    def boom(_value):  # noqa: ANN001
        raise RuntimeError("alert query failed")

    monkeypatch.setattr(idempotency_module, "to_naive_utc", boom)
    record_id = await _begin(wallet_id, "k-2", payload)
    assert record_id


@pytest.mark.anyio
async def test_governed_mcp_new_key_retry_loop_alerts_once(
    client,  # noqa: F811
    clean_database,
    strict_trust_mode,  # noqa: F811
    alert_on,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end: an agent re-sending the same tool call under fresh keys."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tool_name = "retry-loop-alert-tool"
    registry = get_service_registry()
    registry.register_local(
        service_id=tool_name,
        name="Retry Loop Alert Tool",
        description="Pins first-repeat alerting",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda message="ok": {"message": message},
        credits_per_unit=1.0,
        unit_name="call",
    )
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=provisioned["key_id"],
            tool_name=tool_name,
        )
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            for i in range(4):
                resp = await client.post(
                    "/mcp/messages",
                    json=_jsonrpc_body(
                        tool_name=tool_name,
                        wallet_id=wallet_id,
                        request_id=f"loop-{i}",
                        permit_id=permit["permit_id"],
                        idempotency_key=f"loop-key-{i}",
                    ),
                    headers=provisioned["agent_headers"],
                )
                assert "error" not in resp.json(), resp.json()
    finally:
        registry.unregister_local(tool_name)
    alerts = _alerts(caplog)
    assert len(alerts) == 1
    assert alerts[0].wallet_id == wallet_id  # type: ignore[attr-defined]
