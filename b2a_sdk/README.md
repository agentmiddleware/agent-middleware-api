# Agent Middleware Python SDK

Typed async client for the governed MCP trust loop:

`discover → authenticate → authorize → invoke → meter → receipt → audit → govern`

CI builds version `0.5.0` as wheel and source artifacts. Pushing the
`python-sdk-v0.5.0` tag attaches them to a GitHub release. The package is not
published to PyPI.

## Installation

`0.5.0` is the source version here; the newest cut release is
`python-sdk-v0.4.0`. Install the released wheel:

```bash
python -m pip install ./b2a_sdk-0.4.0-py3-none-any.whl
```

Once `python-sdk-v0.5.0` is tagged, the same command with `0.5.0` installs it.

For repository development:

```bash
python -m pip install -e './b2a_sdk[dev]'
```

`httpx` is the only runtime dependency. Offline receipt verification
additionally needs `cryptography`, kept behind an extra:

```bash
python -m pip install './b2a_sdk[verify]'
```

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

## Verifying a receipt offline

`b2a_sdk.receipt_verifier` checks a receipt with no server, no database, and
no credential — it imports nothing from the middleware application. Use it to
audit a receipt handed to you by another agent, or to re-check your own long
after the call.

```python
from b2a_sdk.receipt_verifier import key_set_from_document, verify_bundle

# bundle:   GET /v1/receipts/{receipt_id}/portable   (authorized)
# keys:     GET /.well-known/trust-keys.json         (unauthenticated)
result = verify_bundle(bundle, key_set_from_document(keys))

if result.ok:
    print(result.claims["tool"], result.claims["credits_charged"])
elif result.is_tampered:
    print("receipt does not verify:", result.reason)
else:
    print("cannot determine:", result.status.value, result.reason)
```

That three-way split is deliberate. `is_tampered` is a verdict on the receipt;
`UNKNOWN_KEY`, `MALFORMED`, and `UNSUPPORTED` say only that this verifier could
not decide — usually a stale key set. Treating them alike turns an outage into
a fraud alarm.

The same check from a shell:

```bash
b2a-verify-receipt --bundle receipt.json --keys trust-keys.json
# exit 0 verified, 1 forged, 2 undetermined
```

Pass `--issuer https://api.example.com` to fetch the key set instead of
supplying it, and `--expect-issuer` to require the bundle to name the origin
you meant to audit.

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
