"""Staging-only pilot: reconcile worker against the refund-partner fixture.

Production defaults stay off. This test overrides settings in-process, parks
one ``delivery_uncertain`` call with ``after_effect=hang``, and runs the real
worker against the fixture's ``POST /status``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    ControlPlaneAuditEventModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    ReceiptModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services import upstream_reconcile as reconcile_mod
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import UpstreamMcpAdapter, UpstreamMcpConfiguration
from app.services.upstream_reconcile import (
    RESOLUTION_EVENT,
    UpstreamStatusEndpointProbe,
    resolution_event_id,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

pytestmark = pytest.mark.anyio

PUBLIC_TOOL = "partner.refund.pilot"
UPSTREAM_TOOL = "partner.refund"
TOKEN = "refund-bearer"
CALL_TIMEOUT_SECONDS = 0.5
HANG_SECONDS = 2.0


def _pilot_settings() -> Settings:
    return Settings(
        _env_file=None,
        ENVIRONMENT="local",
        MCP_UPSTREAM_ENABLED=True,
        MCP_UPSTREAM_URL="http://localhost:9000/mcp",
        MCP_UPSTREAM_STATUS_URL="http://localhost:9000/status",
        MCP_UPSTREAM_TOOL_NAME=UPSTREAM_TOOL,
        MCP_UPSTREAM_PUBLIC_TOOL_ID=PUBLIC_TOOL,
        MCP_UPSTREAM_BEARER_TOKEN=TOKEN,
        MCP_UPSTREAM_CREDITS_PER_CALL="2",
        MCP_UPSTREAM_CALL_TIMEOUT_SECONDS=CALL_TIMEOUT_SECONDS,
        UPSTREAM_RECONCILE_WORKER_ENABLED=True,
        UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED=False,
        UPSTREAM_RECONCILE_BACKOFF_SECONDS="1",
    )


def _load_partner(db_path: str) -> Any:
    os.environ["MCP_REFUND_PARTNER_ALLOWED_HOST"] = "localhost:9000"
    os.environ["MCP_REFUND_PARTNER_BEARER_TOKEN"] = TOKEN
    os.environ["MCP_REFUND_PARTNER_CONTROL_TOKEN"] = "refund-control"
    os.environ["MCP_REFUND_PARTNER_DB_PATH"] = db_path
    module_name = "tests.support.mcp_refund_partner_app"
    if module_name in sys.modules:
        raise RuntimeError("refund partner fixture was imported before its env was set")
    from tests.support import mcp_refund_partner_app as partner

    return partner


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


async def _refund_count(wallet_id: str) -> int:
    async with get_session_factory()() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(
                    LedgerEntryModel.wallet_id == wallet_id,
                    LedgerEntryModel.action == "refund",
                )
            )
            or 0
        )


async def test_hang_reconciles_executed_with_debit_standing_and_original_replay(
    client: AsyncClient,
    clean_database: None,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings.model_fields["UPSTREAM_RECONCILE_WORKER_ENABLED"].default is False
    assert (
        Settings.model_fields[
            "UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED"
        ].default
        is False
    )
    settings = _pilot_settings()
    assert settings.UPSTREAM_RECONCILE_WORKER_ENABLED is True
    assert settings.UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED is False

    partner = _load_partner(str(tmp_path / "refund-partner.sqlite3"))
    configuration = UpstreamMcpConfiguration.from_settings(settings)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=partner.app),
        base_url="http://localhost",
        headers={"Authorization": f"Bearer {TOKEN}"},
        follow_redirects=False,
    )
    adapter = UpstreamMcpAdapter(configuration, http_client=http_client)
    registry = get_service_registry()
    registered = False
    try:
        async with partner.mcp_app.router.lifespan_context(partner.mcp_app):
            discovered = await adapter.discover_tool()
            registry.register_upstream(
                service_id=PUBLIC_TOOL,
                name=discovered.name,
                description=discovered.description,
                category=ServiceCategory.AGENT_COMMS,
                executor=adapter,
                input_schema=discovered.input_schema,
                output_schema=discovered.output_schema,
                credits_per_unit=2.0,
                upstream_tool_name=UPSTREAM_TOOL,
                upstream_origin=configuration.origin,
            )
            registered = True

            provisioned = await provision_agent_wallet(client)
            wallet_id = provisioned["agent_wallet_id"]
            permit = await create_tool_permit(
                client,
                wallet_id=wallet_id,
                key_id=provisioned["key_id"],
                tool_name=PUBLIC_TOOL,
                idem_key="sel-333-permit",
            )
            request = {
                "jsonrpc": "2.0",
                "id": "sel-333-hang",
                "method": "tools/call",
                "params": {
                    "name": PUBLIC_TOOL,
                    "arguments": {
                        "refund_ref": "sel-333",
                        "amount_cents": 100,
                        "after_effect": "hang",
                        "hang_seconds": HANG_SECONDS,
                    },
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "sel-333-hang-1",
                    },
                },
            }
            response = await client.post(
                "/mcp/messages",
                json=request,
                headers=provisioned["agent_headers"],
            )
            assert response.status_code == 200
            body = response.json()
            assert body["error"]["message"] == "delivery_uncertain"
            receipt = body["error"]["data"]["receipt"]
            assert receipt["outcome"] == "delivery_uncertain"
            assert partner._totals()["effect_count"] == 1
            refunds_before = await _refund_count(wallet_id)

            async with get_session_factory()() as session:
                attempt = (
                    await session.execute(
                        select(McpDispatchAttemptModel).where(
                            McpDispatchAttemptModel.wallet_id == wallet_id
                        )
                    )
                ).scalar_one()
                wallet_balance = (await session.get(WalletModel, wallet_id)).balance
                await session.execute(
                    update(McpDispatchAttemptModel)
                    .where(McpDispatchAttemptModel.attempt_id == attempt.attempt_id)
                    .values(completed_at=utc_now() - timedelta(seconds=2))
                )
                await session.commit()
                balance_before = wallet_balance
                attempt_id = attempt.attempt_id

            original_build = reconcile_mod.build_configured_probe

            def _build(active: Settings) -> Any:
                assert active.UPSTREAM_RECONCILE_WORKER_ENABLED is True
                probe = original_build(active)
                assert isinstance(probe, UpstreamStatusEndpointProbe)
                probe._probe._transport_adapter._injected_http_client = http_client
                return probe

            monkeypatch.setattr(reconcile_mod, "get_settings", lambda: settings)
            monkeypatch.setattr(reconcile_mod, "build_configured_probe", _build)
            assert settings.UPSTREAM_RECONCILE_WORKER_ENABLED is True
            worker = reconcile_mod.DeliveryUncertainReconcileWorker.from_settings()
            sweep = await worker.run_once()
            assert sweep.probed == 1
            assert sweep.resolved_executed == 1
            assert sweep.refunded == 0

            async with get_session_factory()() as session:
                fresh = await session.get(McpDispatchAttemptModel, attempt_id)
                assert fresh is not None
                stored_receipt = (
                    await session.execute(
                        select(ReceiptModel).where(
                            ReceiptModel.dispatch_attempt_id == attempt_id
                        )
                    )
                ).scalar_one()
                audit = await session.get(
                    ControlPlaneAuditEventModel, resolution_event_id(attempt_id)
                )
                assert audit is not None
                balance_after = (await session.get(WalletModel, wallet_id)).balance
            assert fresh.state == "delivery_uncertain"
            assert fresh.reconcile_status == "executed"
            assert fresh.debit_refunded_at is None
            assert fresh.budget_released_at is None
            assert stored_receipt.outcome == "delivery_uncertain"
            assert stored_receipt.receipt_id == receipt["receipt_id"]
            assert balance_after == balance_before
            assert await _refund_count(wallet_id) == refunds_before
            assert audit.event == RESOLUTION_EVENT
            metadata = json.loads(audit.metadata_json or "{}")
            assert metadata["provider_outcome"] == "executed"
            assert metadata["budget_action"] == "none"
            assert metadata["refund_candidate"] is False

            replay = await client.post(
                "/mcp/messages",
                json=request,
                headers=provisioned["agent_headers"],
            )
            assert replay.status_code == 200
            assert replay.json() == body
            assert partner._totals()["effect_count"] == 1
    finally:
        if registered:
            registry.unregister_local(PUBLIC_TOOL)
        await http_client.aclose()
