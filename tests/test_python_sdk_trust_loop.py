"""End-to-end proof that the packaged Python SDK drives the governed loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from b2a_sdk import AgentMiddlewareClient, PermitRequest
from tests.test_trust_helpers import provision_agent_wallet


@pytest.mark.anyio
async def test_python_sdk_permit_invoke_replay_receipt_and_evidence(
    clean_database,
) -> None:
    registry = get_service_registry()
    calls = 0

    def sdk_echo(message: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"message": message}

    registry.register_local(
        service_id="sdk-trust-echo",
        name="SDK Trust Echo",
        description="SDK governed-loop integration tool",
        category=ServiceCategory.AGENT_COMMS,
        func=sdk_echo,
        credits_per_unit=2,
        unit_name="call",
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as raw_client:
            provisioned = await provision_agent_wallet(raw_client)
            wallet_id = provisioned["agent_wallet_id"]
            api_key = provisioned["agent_headers"]["X-API-Key"]

            async with AgentMiddlewareClient(
                api_key=api_key,
                base_url="http://test",
                transport=ASGITransport(app=app),
            ) as sdk:
                tools = await sdk.discover_tools()
                assert any(tool.name == "sdk-trust-echo" for tool in tools)

                permit = await sdk.create_permit(
                    PermitRequest(
                        issuer_wallet_id=wallet_id,
                        subject_wallet_id=wallet_id,
                        subject_key_id=provisioned["key_id"],
                        scopes=["tool:sdk-trust-echo:invoke", "billing:charge"],
                        allowed_tools=["sdk-trust-echo"],
                        max_credits=Decimal("20"),
                        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)),
                    ),
                    idempotency_key="sdk-permit-1",
                )

                first = await sdk.invoke_tool(
                    "sdk-trust-echo",
                    {"message": "hello"},
                    wallet_id=wallet_id,
                    permit_id=permit.permit_id,
                    idempotency_key="sdk-invoke-1",
                )
                replay = await sdk.invoke_tool(
                    "sdk-trust-echo",
                    {"message": "hello"},
                    wallet_id=wallet_id,
                    permit_id=permit.permit_id,
                    idempotency_key="sdk-invoke-1",
                )

                fetched = await sdk.get_receipt(first.receipt.receipt_id)
                verification = await sdk.verify_receipt(first.receipt.receipt_id)
                evidence = await sdk.get_evidence(first.receipt.receipt_id)

        assert calls == 1
        assert replay.receipt.receipt_id == first.receipt.receipt_id
        assert fetched.ledger_entry_id == first.receipt.ledger_entry_id
        assert verification.valid is True
        assert evidence.valid is True
        assert evidence.verification["receipt_signature"] == "ok"
    finally:
        registry.unregister_local("sdk-trust-echo")
