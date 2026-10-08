"""Minimal AWI SDK example: discover, start a session, run one action.

Needs a local server with proof surfaces enabled plus a real API key,
wallet, and permit. Fill in the placeholders and run:

    python -m pip install ./awi_sdk/python
    python awi_sdk/python/examples/quickstart.py
"""

import asyncio

from awi_sdk import AWIClient, AWIClientConfig

BASE_URL = "http://localhost:8000"
API_KEY = "your-key"
WALLET_ID = "wallet-123"
PERMIT_ID = "permit-from-POST-/v1/permits"


async def main() -> None:
    client = AWIClient(AWIClientConfig(base_url=BASE_URL, api_key=API_KEY, wallet_id=WALLET_ID))
    try:
        actions = await client.list_action_definitions()
        print(f"{len(actions)} actions available")
        print("example:", actions[0].action, "-", actions[0].description)

        session = await client.create_session("https://shop.example.com")
        print("session:", session["session_id"])

        result = await client.execute_typed(
            session["session_id"],
            "search_and_sort",
            {"query": "laptops", "sort_by": "price"},
            permit_id=PERMIT_ID,
            idempotency_key="quickstart-search-1",
        )
        print("status:", result.status)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
