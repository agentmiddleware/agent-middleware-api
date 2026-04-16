# B2A SDK

Python SDK for the Agent-Native Middleware API.

## Installation

```bash
pip install b2a-sdk
```

## Quick Start

```python
from b2a_sdk import B2AClient, monitored, billable

# Initialize the client
b2a = B2AClient(api_key="agt-your-api-key")

# Monitor a function (telemetry is fire-and-forget)
@monitored(b2a, service_name="web_scraper")
async def scrape_website(url: str):
    # Your agent logic here...
    pass

# Gate execution behind billing
@billable(b2a, wallet_id="agt-123", service_category="content_factory", units=5.0)
async def generate_video(url: str):
    # This only runs if wallet has 5+ credits
    pass
```

## Decorators

### `@monitored`

Wires a function to the Autonomous PM for telemetry:

```python
@monitored(b2a, service_name="my_service", capture_args=True)
async def my_function(url: str):
    return url
```

### `@billable`

Gates execution behind the billing engine:

```python
@billable(b2a, wallet_id="wallet-123", service_category="iot_bridge", units=2.0)
async def send_iot_message(device_id: str):
    pass
```

### `@combined`

Combines both decorators:

```python
@combined(
    b2a,
    wallet_id="wallet-123",
    service_category="content_factory",
    service_name="video_generator",
    units=5.0,
)
async def generate_video(url: str):
    pass
```

## Client Usage

```python
import asyncio
from b2a_sdk import B2AClient, InsufficientFundsError

async def main():
    b2a = B2AClient(api_key="agt-your-api-key")

    try:
        # Charge a wallet
        result = await b2a.charge("wallet-123", "iot_bridge", units=10)
        print(f"Charged: {result}")

        # Create a wallet
        wallet = await b2a.create_sponsor_wallet(
            sponsor_name="Test Corp",
            email="test@example.com",
            initial_credits=10000.0,
        )

        # Get pricing
        pricing = await b2a.get_pricing()

    except InsufficientFundsError as e:
        print(f"Wallet needs top-up: {e.top_up_url}")

    finally:
        await b2a.close()

asyncio.run(main())
```

## Environment Variables

```bash
# Optional: Set default base URL
export B2A_BASE_URL=https://api.agentnative.io
```

## License

MIT
