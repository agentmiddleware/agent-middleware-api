"""
Dry-Run Sandbox Example
=======================

Demonstrates how agents can safely test billing operations without
affecting real wallet balances or triggering velocity monitoring.

Usage:
    python examples/dry_run_example.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from b2a_sdk import B2AClient
from b2a_sdk.decorators import billable


b2a = B2AClient(
    api_key=os.getenv("B2A_API_KEY", "test-key"),
    base_url=os.getenv("B2A_API_URL", "http://localhost:8000"),
    wallet_id=os.getenv("B2A_WALLET_ID", "sponsor-0"),
)


@billable(b2a, wallet_id="sponsor-0", service_category="content_factory", units=10.0)
async def generate_video_hook(url: str, style: str = "cinematic") -> dict:
    """Simulate a video generation call."""
    return {
        "video_url": f"https://example.com/{hash(url)}.mp4",
        "style": style,
        "status": "generated",
    }


@billable(b2a, wallet_id="sponsor-0", service_category="media_engine", units=5.0)
async def distribute_clip(clip_id: str, platform: str = "youtube") -> dict:
    """Simulate a clip distribution call."""
    return {
        "clip_id": clip_id,
        "platform": platform,
        "status": "distributed",
    }


@billable(b2a, wallet_id="sponsor-0", service_category="iot_bridge", units=1.0)
async def send_iot_message(device_id: str, message: str) -> dict:
    """Simulate an IoT message send."""
    return {
        "device_id": device_id,
        "message": message,
        "status": "sent",
    }


async def demo_simulation():
    """Demonstrate dry-run simulation."""
    print("\n" + "=" * 60)
    print("B2A Dry-Run Sandbox Demo")
    print("=" * 60)

    try:
        await b2a.create_sponsor_wallet(
            sponsor_name="Demo Sponsor",
            email="demo@example.com",
            initial_credits=10000.0,
        )
        print("\n✓ Created sponsor wallet with 10,000 credits")
    except Exception as e:
        print(f"\n⚠ Wallet may already exist: {e}")

    print("\n--- Scenario 1: Estimate Cost of Multi-Step Workflow ---")
    print("Agent wants to: generate_video → distribute_clip → send_iot_message")
    print("But doesn't know if it fits the budget...")

    async with b2a.simulate_session(wallet_id="sponsor-0") as sim:
        print(f"\nSession started: {sim.session_id}")
        print(f"Initial virtual balance: {sim.total_cost} credits")

        result1 = await generate_video_hook("https://example.com/video1.mp4")
        print(f"\n1. Simulated generate_video:")
        print(f"   Result: {result1}")
        print(f"   Session total: {sim.total_cost} credits")

        result2 = await distribute_clip("clip-123", platform="tiktok")
        print(f"\n2. Simulated distribute_clip:")
        print(f"   Result: {result2}")
        print(f"   Session total: {sim.total_cost} credits")

        result3 = await send_iot_message("device-001", "status=ok")
        print(f"\n3. Simulated send_iot_message:")
        print(f"   Result: {result3}")
        print(f"   Session total: {sim.total_cost} credits")

        print(f"\n{'=' * 60}")
        print(f"SIMULATION SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total estimated cost: {sim.total_cost} credits")
        print(f"Number of operations: {sim.charge_count}")
        print(f"Would succeed: {sim.would_succeed}")

        if sim.would_succeed:
            print("\n✅ Agent decides: Budget is sufficient. Proceeding with real execution!")
        else:
            print("\n❌ Agent decides: Insufficient budget. Need to top up first.")

    print("\n--- Scenario 2: Single-Shot Estimation ---")
    print("Quick estimate without session tracking:")

    result = await b2a.simulate_charge(
        wallet_id="sponsor-0",
        service_category="content_factory",
        units=100.0,
        description="Bulk video generation",
    )

    print(f"\nSingle charge simulation:")
    print(f"  Would charge: {result['credits_would_charge']} credits")
    print(f"  Virtual balance before: {result['simulated_balance_before']}")
    print(f"  Virtual balance after: {result['simulated_balance_after']}")
    print(f"  Would succeed: {result['would_succeed']}")

    print("\n--- Scenario 3: Compare Workflows ---")
    print("Comparing two different workflow strategies...")

    workflow_a_total = 0
    async with b2a.simulate_session(wallet_id="sponsor-0") as sim:
        for i in range(3):
            await generate_video_hook(f"url-{i}")
        workflow_a_total = sim.total_cost

    workflow_b_total = 0
    async with b2a.simulate_session(wallet_id="sponsor-0") as sim:
        for i in range(3):
            await send_iot_message(f"device-{i}", "ping")
        workflow_b_total = sim.total_cost

    print(f"\nWorkflow A (3x video generation): {workflow_a_total} credits")
    print(f"Workflow B (3x IoT messages): {workflow_b_total} credits")

    if workflow_a_total < workflow_b_total:
        print("\n✅ Workflow A is more cost-effective!")
    else:
        print("\n✅ Workflow B is more cost-effective!")

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


async def main():
    try:
        await demo_simulation()
    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure the B2A API is running at http://localhost:8000")
        print("Or set B2A_API_URL environment variable.")


if __name__ == "__main__":
    asyncio.run(main())
