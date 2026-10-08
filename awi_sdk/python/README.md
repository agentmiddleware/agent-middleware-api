# AWI Python SDK

Async Python client for the Agentic Web Interface (AWI) routes.

> **Proof surface.** The `/v1/awi/*` routes are frozen proof surfaces,
> unmounted in production-like deployments (`ENABLE_PROOF_SURFACES=false`).
> This client only works against a server started with proof surfaces
> enabled. See `docs/PROOF_SURFACES.md`. The product-vs-demo decision is
> still open; do not sell this as a production integration.

## Install

Not published to PyPI. Install from this checkout:

```bash
python -m pip install ./awi_sdk/python
```

## Quick start

```python
import asyncio

from awi_sdk import AWIClient, AWIClientConfig


async def main() -> None:
    client = AWIClient(
        AWIClientConfig(
            base_url="http://localhost:8000",
            api_key="your-key",
            wallet_id="wallet-123",
        )
    )
    try:
        # Typed vocabulary menu
        for action in await client.list_action_definitions():
            print(action.action, action.description)

        session = await client.create_session("https://shop.example.com")
        result = await client.execute_typed(
            session["session_id"],
            "search_and_sort",
            {"query": "laptops", "sort_by": "price"},
            permit_id="permit-from-POST-/v1/permits",
            idempotency_key="search-laptops-1",
        )
        print(result.status)
    finally:
        await client.close()


asyncio.run(main())
```

A runnable version lives in `examples/quickstart.py`.

## Behavior notes

- `execute` requires `permit_id` and `idempotency_key`. Blank or
  oversize keys raise `ValueError` before any network call.
- Transient failures (transport errors, 408/429/502/503/504) are
  retried up to `AWIClientConfig.max_retries` times after the first
  attempt, reusing the same idempotency key. Permit refusals,
  conflicts, and other client errors are never retried.
- Error responses raise typed errors from `awi_sdk.errors`
  (`AuthenticationError`, `PermitDeniedError`,
  `IdempotencyConflictError`, ...). All subclass
  `httpx.HTTPStatusError`, so existing `except httpx.HTTPStatusError`
  handlers keep working.
- Redirects are never followed, so `X-API-Key` cannot leak to
  another host.
- `execute` returns the raw server dict (including the receipt
  envelope). Use `execute_typed` for the parsed
  `AWIExecutionResponse` model.
