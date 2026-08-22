"""Test to reproduce max_calls_per_tool race condition."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import ReceiptModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from sqlalchemy import select, func
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _register_test_tool(tool_name: str, credits: float = 1.0):
    """Register a simple echo tool for testing."""
    registry = get_service_registry()

    def test_echo(input: str = "ok") -> dict:
        return {"message": input}

    registry.register_local(
        service_id=tool_name,
        name="Test Echo",
        description="Test tool for max_calls race",
        category=ServiceCategory.AGENT_COMMS,
        func=test_echo,
        credits_per_unit=credits,
        unit_name="call",
    )
    return registry


async def _invoke_governed(
    client: AsyncClient,
    *,
    wallet_id: str,
    permit_id: str,
    tool_name: str,
    arguments: dict | None = None,
    idem_key: str = "invoke-1",
    headers: dict | None = None,
):
    """Invoke a tool under a governed permit via JSON-RPC."""
    resp = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
                "mcpContext": {
                    "wallet_id": wallet_id,
                    "permit_id": permit_id,
                    "idempotency_key": idem_key,
                },
            },
        },
        headers=headers or BOOTSTRAP_HEADERS,
    )
    return resp


@pytest.mark.anyio
async def test_max_calls_concurrent_race(client, clean_database):
    """Concurrent calls can exceed max_calls_per_tool limit due to read-time-only check."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "race-test-echo"

    _register_test_tool(tool_name, credits=1.0)
    try:
        # Create permit with limit of 2 calls
        permit_resp = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": wallet_id,
                "subject_wallet_id": wallet_id,
                "subject_key_id": key_id,
                "allowed_tools": [tool_name],
                "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                "max_credits": 50,
                "max_calls_per_tool": {tool_name: 2},
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=30)
                ).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "race-permit-1"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]

        # Launch 3 concurrent calls
        tasks = [
            _invoke_governed(
                client,
                wallet_id=wallet_id,
                permit_id=permit_id,
                tool_name=tool_name,
                arguments={"input": f"call{i}"},
                idem_key=f"race-{i}",
                headers=agent_headers,
            )
            for i in range(1, 4)
        ]
        
        responses = await asyncio.gather(*tasks)
        
        # Count successful calls
        success_count = sum(1 for r in responses if r.status_code == 200 and "result" in r.json())
        error_count = sum(1 for r in responses if "error" in r.json())
        
        print(f"\nSuccessful calls: {success_count}, Errors: {error_count}")
        for i, r in enumerate(responses, 1):
            body = r.json()
            if "error" in body:
                print(f"Call {i}: ERROR - {body['error'].get('message', 'unknown')}")
            else:
                print(f"Call {i}: SUCCESS")
        
        # Verify receipt count in database
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(func.count()).select_from(ReceiptModel).where(
                    ReceiptModel.permit_id == permit_id,
                    ReceiptModel.tool == tool_name,
                    ReceiptModel.outcome == "success",
                )
            )
            actual_receipt_count = int(result.scalar() or 0)
            print(f"Actual successful receipts in DB: {actual_receipt_count}")
        
        # BUG: If more than 2 calls succeeded, the limit was not enforced atomically
        assert actual_receipt_count <= 2, f"max_calls_per_tool=2 was violated: {actual_receipt_count} successful receipts exist"
        
    finally:
        get_service_registry().unregister_local(tool_name)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
