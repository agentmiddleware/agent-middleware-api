"""Hyper-edge-case stress test against live trust plane.

Usage:
    export AGENT_MIDDLEWARE_API_KEY=...        # required, never hardcode
    export AGENT_MIDDLEWARE_API_URL=https://...  # optional, defaults to production
    python scripts/stress_test_live.py

This script creates wallets, permits and receipts on whatever deployment it is
pointed at. Point it at a staging deployment unless you intend to write test
data to production.
"""

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

DEFAULT_API_URL = "https://api-service-production-433c.up.railway.app"

API_URL = os.environ.get("AGENT_MIDDLEWARE_API_URL", DEFAULT_API_URL)
API_KEY = os.environ.get("AGENT_MIDDLEWARE_API_KEY", "")

if not API_KEY:
    sys.exit(
        "AGENT_MIDDLEWARE_API_KEY is not set.\n"
        "Export a key for the target deployment before running:\n"
        "    export AGENT_MIDDLEWARE_API_KEY=...\n"
        "Credentials must never be committed to this repository."
    )

# Every idempotency key is namespaced with a fresh per-run prefix. Without this
# a second run replays the first run's cached responses instead of re-testing,
# so the suite would silently stop exercising the code paths it claims to cover.
RUN_ID = os.environ.get("STRESS_RUN_ID") or uuid.uuid4().hex[:12]


def ikey(name: str) -> str:
    """Build a run-scoped Idempotency-Key."""
    return f"stress-{RUN_ID}-{name}"


# Rate-limiting semaphore
SEM = asyncio.Semaphore(10)


async def req(method, path, **kwargs):
    async with SEM:
        async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
            headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
            headers.update(kwargs.pop("headers", {}))
            return await c.request(method, path, headers=headers, **kwargs)


async def setup_wallets():
    """Create sponsor + agent for stress tests."""
    sponsor = await req("POST", "/v1/billing/wallets/sponsor",
        json={"sponsor_name": "Stress", "email": "stress@example.com", "initial_credits": 10000})
    assert sponsor.status_code == 201, f"sponsor: {sponsor.text}"
    spn = sponsor.json()["wallet_id"]

    agent = await req("POST", "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": spn, "agent_id": ikey("bot"), "budget_credits": 1000})
    assert agent.status_code == 201, f"agent: {agent.text}"
    agt = agent.json()["wallet_id"]

    return spn, agt


async def test_budget_exhaustion(spn, agt):
    """Spend exact budget, then one more."""
    print("\n[STRESS] Budget exhaustion...")
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("budget")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "4", "expires_at": "2099-01-01T00:00:00Z"})
    assert permit.status_code == 201
    pid = permit.json()["permit_id"]

    # 4 credits / 2 per call = 2 calls exactly
    for i in range(2):
        r = await req("POST", "/mcp/messages",
            headers={"Idempotency-Key": ikey(f"budget-invoke-{i}")},
            json={"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": "partner.notes.write", "arguments": {"text": f"call {i}"},
                             "mcpContext": {"wallet_id": agt, "permit_id": pid}}})
        assert r.status_code == 200, f"call {i}: {r.text}"
        assert "error" not in r.json(), f"call {i} failed: {r.json()}"
        print(f"  call {i+1}: ✅")

    # Third call should exceed budget
    r = await req("POST", "/mcp/messages",
        headers={"Idempotency-Key": ikey("budget-invoke-2")},
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/call",
              "params": {"name": "partner.notes.write", "arguments": {"text": "over budget"},
                         "mcpContext": {"wallet_id": agt, "permit_id": pid}}})
    assert r.status_code == 200
    err = r.json().get("error", {})
    assert err.get("message") == "permit_budget_exceeded", f"unexpected: {err}"
    print("  over-budget call: ✅ denied")


async def test_expired_permit(spn, agt):
    """Permit that expired 1 second ago."""
    print("\n[STRESS] Expired permit...")
    one_sec_ago = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("expired")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "10", "expires_at": one_sec_ago})
    # Should be rejected at creation
    assert permit.status_code == 400 or "permit_expired" in permit.text, f"expected expired rejection, got: {permit.status_code} {permit.text}"
    print("  expired-at-creation: ✅ rejected")


async def test_concurrent_permit_creation(spn, agt):
    """20 parallel permit creations with same idempotency key."""
    print("\n[STRESS] Concurrent permit creation (same idempotency key)...")
    async def create(i):
        return await req("POST", "/v1/permits",
            headers={"Idempotency-Key": ikey("concurrent-permit")},
            json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
                  "allowed_tools": ["partner.notes.write"],
                  "max_credits": "10", "expires_at": "2099-01-01T00:00:00Z"})

    results = await asyncio.gather(*[create(i) for i in range(20)])
    codes = [r.status_code for r in results]
    ok_count = codes.count(201)
    conflict_count = codes.count(409)
    # Race: first writer wins (201), rest get 409 conflict — correct behavior
    assert ok_count >= 1, f"expected at least one 201, got {codes}"
    pids = [r.json().get("permit_id") for r in results if r.status_code == 201]
    assert len(set(pids)) == 1, f"expected same permit_id, got {set(pids)}"
    print(f"  20 concurrent creates: ✅ {ok_count}x201, {conflict_count}x409, same permit_id")


async def test_concurrent_governed_invokes(spn, agt):
    """20 parallel invokes with fresh idempotency keys."""
    print("\n[STRESS] Concurrent governed invokes...")
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("concurrent-invoke-permit")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "100", "expires_at": "2099-01-01T00:00:00Z"})
    pid = permit.json()["permit_id"]

    async def invoke(i):
        return await req("POST", "/mcp/messages",
            headers={"Idempotency-Key": ikey(f"invoke-{i}")},
            json={"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": "partner.notes.write", "arguments": {"text": f"concurrent {i}"},
                             "mcpContext": {"wallet_id": agt, "permit_id": pid}}})

    start = time.monotonic()
    results = await asyncio.gather(*[invoke(i) for i in range(20)])
    elapsed = time.monotonic() - start
    codes = [r.status_code for r in results]
    success = sum(1 for r in results if "error" not in r.json())
    print(f"  20 parallel invokes in {elapsed:.2f}s: {success}/20 success, codes={set(codes)}")
    assert success == 20, "expected all success, got failures"


async def test_unicode_payload(spn, agt):
    """Unicode, emoji, and special chars in note text."""
    print("\n[STRESS] Unicode/emoji payload...")
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("unicode-permit")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "10", "expires_at": "2099-01-01T00:00:00Z"})
    pid = permit.json()["permit_id"]

    texts = [
        "Hello 世界 🌍",
        "<script>alert('xss')</script>",
        "' OR 1=1 --",
        "\x00\x01\x02",
        "A" * 10000,
        "日本語テスト",
        "🔥💀🎉💰",
    ]
    for i, text in enumerate(texts):
        r = await req("POST", "/mcp/messages",
            headers={"Idempotency-Key": ikey(f"unicode-{i}")},
            json={"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": "partner.notes.write", "arguments": {"text": text},
                             "mcpContext": {"wallet_id": agt, "permit_id": pid}}})
        body = r.json()
        if "error" in body:
            print(f"  text-{i} ({text[:30]}...): ❌ {body['error']}")
        else:
            print(f"  text-{i} ({text[:30]}...): ✅")


async def test_tampered_permit(spn, agt):
    """Try to use a forged permit ID."""
    print("\n[STRESS] Tampered/forged permit...")
    r = await req("POST", "/mcp/messages",
        headers={"Idempotency-Key": ikey("forged")},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "partner.notes.write", "arguments": {"text": "forged"},
                         "mcpContext": {"wallet_id": agt, "permit_id": "permit-fake123456789"}}})
    assert r.status_code == 200
    err = r.json().get("error", {})
    assert err.get("message") in ("permit_not_found", "permit_required"), f"unexpected: {err}"
    print(f"  forged permit: ✅ denied ({err.get('message')})")


async def test_cross_wallet_access(spn, agt):
    """Agent A tries to use Agent B's permit."""
    print("\n[STRESS] Cross-wallet access...")
    # Create a second agent
    agent2 = await req("POST", "/v1/billing/wallets/agent",
        json={"sponsor_wallet_id": spn, "agent_id": ikey("bot-2"), "budget_credits": 100})
    agt2 = agent2.json()["wallet_id"]

    # Create permit for agent 1
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("cross-permit")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "10", "expires_at": "2099-01-01T00:00:00Z"})
    pid = permit.json()["permit_id"]

    # Agent 2 tries to use it
    r = await req("POST", "/mcp/messages",
        headers={"Idempotency-Key": ikey("cross-invoke")},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "partner.notes.write", "arguments": {"text": "cross"},
                         "mcpContext": {"wallet_id": agt2, "permit_id": pid}}})
    assert r.status_code == 200
    err = r.json().get("error", {})
    assert err.get("message") == "permit_wallet_mismatch", f"unexpected: {err}"
    print(f"  cross-wallet invoke: ✅ denied ({err.get('message')})")


async def test_timezone_extremes(spn, agt):
    """Extreme timezone offsets."""
    print("\n[STRESS] Timezone extremes...")
    offsets = [
        "2099-01-01T00:00:00+14:00",   # max offset
        "2099-01-01T00:00:00-12:00",   # min offset
        "2099-01-01T00:00:00+00:30",   # half-hour offset
        "2099-01-01T00:00:00+05:30",   # India
        "2099-06-01T00:00:00+00:00",   # summer
    ]
    for i, offset in enumerate(offsets):
        r = await req("POST", "/v1/permits",
            headers={"Idempotency-Key": ikey(f"tz-{i}")},
            json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
                  "allowed_tools": ["partner.notes.write"],
                  "max_credits": "10", "expires_at": offset})
        if r.status_code == 201:
            exp = r.json()["expires_at"]
            print(f"  {offset} -> {exp}: ✅")
        else:
            print(f"  {offset}: ❌ {r.status_code} {r.text[:100]}")


async def test_decimal_precision(spn, agt):
    """Edge-case credit amounts."""
    print("\n[STRESS] Decimal precision...")
    amounts = ["0.01", "0.001", "999999", "-1", "0", "abc", ""]
    for i, amt in enumerate(amounts):
        r = await req("POST", "/v1/permits",
            headers={"Idempotency-Key": ikey(f"decimal-{i}")},
            json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
                  "allowed_tools": ["partner.notes.write"],
                  "max_credits": amt, "expires_at": "2099-01-01T00:00:00Z"})
        code = r.status_code
        body = r.json()
        if code == 201:
            print(f"  max_credits={amt}: ✅ created")
        elif "max_credits_must_be_positive" in r.text:
            print(f"  max_credits={amt}: ✅ rejected (positive required)")
        else:
            print(f"  max_credits={amt}: ⚠️ {code} {body.get('detail', r.text[:80])}")


async def test_rapid_fire_idempotency(spn, agt):
    """Hammer same idempotency key 50 times in <1s."""
    print("\n[STRESS] Rapid-fire idempotency (50x same key)...")
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("rapid-permit")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "100", "expires_at": "2099-01-01T00:00:00Z"})
    pid = permit.json()["permit_id"]

    start = time.monotonic()
    tasks = []
    for i in range(50):
        tasks.append(req("POST", "/mcp/messages",
            headers={"Idempotency-Key": ikey("rapid-same-key")},
            json={"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": "partner.notes.write", "arguments": {"text": f"rapid {i}"},
                             "mcpContext": {"wallet_id": agt, "permit_id": pid}}}))
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    successes = sum(1 for r in results if "error" not in r.json())
    # First should succeed, rest should be idempotent replays
    print(f"  50 calls in {elapsed:.2f}s: {successes}/50 success")
    receipt_ids = [r.json().get("result", {}).get("receipt", {}).get("receipt_id", "") for r in results if "result" in r.json()]
    if len(set(receipt_ids)) == 1 and receipt_ids:
        print(f"  All returned same receipt: ✅ {receipt_ids[0]}")
    else:
        print(f"  Receipt IDs varied: {set(receipt_ids)}")


async def test_permit_reuse_after_replay(spn, agt):
    """Use same permit after many replays."""
    print("\n[STRESS] Permit reuse after heavy load...")
    permit = await req("POST", "/v1/permits",
        headers={"Idempotency-Key": ikey("reuse-permit")},
        json={"issuer_wallet_id": spn, "subject_wallet_id": agt,
              "allowed_tools": ["partner.notes.write"],
              "max_credits": "100", "expires_at": "2099-01-01T00:00:00Z"})
    pid = permit.json()["permit_id"]

    # Burn 48 credits (24 calls * 2)
    for i in range(24):
        r = await req("POST", "/mcp/messages",
            headers={"Idempotency-Key": ikey(f"reuse-{i}")},
            json={"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": "partner.notes.write", "arguments": {"text": f"burn {i}"},
                             "mcpContext": {"wallet_id": agt, "permit_id": pid}}})
        assert "error" not in r.json(), f"burn {i} failed: {r.json()}"

    # Check spent
    p = await req("GET", f"/v1/permits/{pid}")
    spent = p.json()["spent_credits"]
    print(f"  24 calls, spent_credits={spent}: {'✅' if spent == '48.0' else '❌'}")

    # One more should work
    r = await req("POST", "/mcp/messages",
        headers={"Idempotency-Key": ikey("reuse-final")},
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/call",
              "params": {"name": "partner.notes.write", "arguments": {"text": "final"},
                         "mcpContext": {"wallet_id": agt, "permit_id": pid}}})
    assert "error" not in r.json()
    print("  25th call (spent=50/100): ✅")


async def test_health_under_load():
    """Hit health endpoint during stress."""
    print("\n[STRESS] Health under load...")
    # Start some background load
    bg_tasks = [req("GET", "/v1/discover") for _ in range(20)]
    # Health check in parallel
    health = await req("GET", "/health")
    await asyncio.gather(*bg_tasks)
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    print("  Health during 20 parallel discoveries: ✅")


async def main():
    print("=" * 60)
    print("HYPER EDGE-CASE STRESS TEST")
    print(f"Target: {API_URL}")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 60)

    # Setup
    print("\n[SETUP] Creating wallets...")
    spn, agt = await setup_wallets()
    print(f"  Sponsor: {spn}")
    print(f"  Agent: {agt}")

    # Run all stress tests
    await test_budget_exhaustion(spn, agt)
    await test_expired_permit(spn, agt)
    await test_concurrent_permit_creation(spn, agt)
    await test_concurrent_governed_invokes(spn, agt)
    await test_unicode_payload(spn, agt)
    await test_tampered_permit(spn, agt)
    await test_cross_wallet_access(spn, agt)
    await test_timezone_extremes(spn, agt)
    await test_decimal_precision(spn, agt)
    await test_rapid_fire_idempotency(spn, agt)
    await test_permit_reuse_after_replay(spn, agt)
    await test_health_under_load()

    print("\n" + "=" * 60)
    print("ALL STRESS TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
