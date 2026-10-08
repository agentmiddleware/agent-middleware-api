# Agent Middleware AWI Python SDK

Async Python client for the Agentic Web Interface (AWI) lifecycle:
discover actions, open sessions, execute steps, fetch representations,
and pause, resume, or steer a running session.

The distribution `agent-middleware-awi` is not published to PyPI.
Work from a checkout of this repository.

## Installation

Install the version in this checkout:

```bash
python -m pip install -e awi_sdk/python
```

Run that command from the repository root. It needs the `httpx`
dependency, which pip resolves from PyPI during the install.

## Quick start

```python
import asyncio

from awi_sdk import AWIClient, AWIClientConfig

async def main() -> None:
    config = AWIClientConfig(
        base_url="http://localhost:8000",
        api_key="your-api-key",
        wallet_id="agent-001",
    )
    async with AWIClient(config) as client:
        session = await client.create_session("https://example.com")
        print(session.session_id)

asyncio.run(main())
```

## Status

Source-only alpha (`0.1.0`, MIT). No wheel is published to an
index; every install path in this file points at the checkout.
See `CHANGELOG` notes in the repository root for what the client
covers and what still needs a live gateway.
