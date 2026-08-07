# Agent Middleware Python SDK

Typed async client for the governed MCP trust loop:

`discover → authenticate → authorize → invoke → meter → receipt → audit → govern`

CI builds version `0.4.0` as wheel and source artifacts. Pushing the
`python-sdk-v0.4.0` tag attaches them to a GitHub release. The package is not
published to PyPI.

## Installation

Install a downloaded release wheel:

```bash
python -m pip install ./b2a_sdk-0.4.0-py3-none-any.whl
```

For repository development:

```bash
python -m pip install -e './b2a_sdk[dev]'
```

`httpx` is the only runtime dependency.

## Governed tool call

```python
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from b2a_sdk import AgentMiddlewareClient, PermitRequest


async def main() -> None:
    async with AgentMiddlewareClient(
        api_key="agt-your-api-key",
        base_url="https://your-gateway.example.com",
    ) as client:
        tools = await client.discover_tools()
        tool = next(item for item in tools if item.name == "partner.search")

        permit = await client.create_permit(
            PermitRequest(
                issuer_wallet_id="agt-wallet",
                subject_wallet_id="agt-wallet",
                subject_key_id="key-runtime",
                scopes=[f"tool:{tool.name}:invoke", "billing:charge"],
                allowed_tools=[tool.name],
                max_credits=Decimal("25"),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            ),
            idempotency_key="permit-run-001",
        )

        invocation = await client.invoke_tool(
            tool.name,
            {"query": "quarterly risk"},
            wallet_id="agt-wallet",
            permit_id=permit.permit_id,
            idempotency_key="invoke-run-001",
        )

        verification = await client.verify_receipt(
            invocation.receipt.receipt_id
        )
        evidence = await client.get_evidence(invocation.receipt.receipt_id)
        assert verification.valid and evidence.valid


asyncio.run(main())
```

Callers must provide nonblank idempotency keys when creating permits and
invoking tools. Reusing a key with a different request raises
`IdempotencyConflictError`.

If a remote tool was dispatched but its outcome could not be confirmed,
`invoke_tool` raises `DeliveryUncertainError`. Its `receipt_id` identifies the
signed, charged uncertainty receipt; the SDK never retries the dispatch.

## Compatibility

`B2AClient` remains available for existing integrations and emits a
`DeprecationWarning`. Legacy wallet, telemetry, dry-run, decorator, and edge
client methods remain available during the `0.4.x` transition. New code should
use `AgentMiddlewareClient` and the typed trust-loop methods.

## Build and test

```bash
uv build b2a_sdk
python -m pytest b2a_sdk/tests
ruff check b2a_sdk/src b2a_sdk/tests
```
