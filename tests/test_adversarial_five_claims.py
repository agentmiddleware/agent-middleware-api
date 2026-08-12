"""In-process adversarial pass over the five trust-plane claims.

This module is the repo-level complement to the two credentialed HTTP
batteries — ``scripts/adversarial_battery.py`` (against a deployment you
operate) and ``scripts/red_team_trust_plane.py`` (a local SQLite red-team).
Those drive the plane from the *outside*. Two of the five claims cannot be
broken from outside without operator credentials and cannot be induced over
the wire at all, so they are proven here, against the real FastAPI routers and
services, where a test can seed a scoped permit and drive an upstream to die
mid-flight:

    Claim 1 — Charge-once under retry.
        One idempotency key returns the original receipt with no second
        execution and no second debit. Also exercised live (deliberate retry).

    Claim 2 — Budget over-spend containment.  [credential-only]
        A permit cannot authorize spend beyond its cap, cumulatively across a
        sequence of calls, and a denied call moves no money. The live battery
        explicitly does NOT exercise this (it needs a tool with a known
        per-call cost and a seeded permit) — see the note in
        ``scripts/adversarial_battery.py`` and ``docs/PROOF_MATRIX.md``.

    Claim 3 — Interrupted-invocation accounting.  [credential-only]
        Every governed invocation ends in exactly one signed terminal
        accounting. A death *after* the dispatch checkpoint stays charged
        (``delivery_uncertain``) and is never redispatched on replay; a death
        *before* it refunds to a net-zero charge without ever executing. An
        induced timeout cannot be turned into a free retry or refund. A remote
        adversary cannot induce these boundaries deterministically; a test can.

    Claim 4 — Signed, offline-verifiable receipts.
        A receipt exported for a stranger verifies offline against the
        unauthenticated key document, through the SDK verifier that imports
        none of this application, and a single flipped byte is detected as
        tampering. This is the "receipt verification" step of the stranger
        test.

    Claim 5 — Authority-before-money denial.
        An out-of-scope attempt is denied with a specific reason *before* any
        money moves, and the denial itself is a signed receipt carrying no
        ledger linkage. The full ten-reason denial matrix lives in
        ``scripts/red_team_trust_plane.py``; this asserts the load-bearing
        invariant (no debit, signed denial) in the same suite as the rest.

Where a claim is already covered exhaustively elsewhere, this module asserts a
single representative adversarial case and cross-references the fuller suite,
rather than duplicating it. The new depth is in claims 2 and 3.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.permits import get_permit_service
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import (
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpPreDispatchError,
    UpstreamMcpResult,
)
from b2a_sdk.receipt_verifier import (
    VerificationStatus,
    key_set_from_document,
    verify_bundle,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL_COST = 2.0
WALLET_START = Decimal("1000")  # provision_agent_wallet seeds budget_credits=1000


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


# --------------------------------------------------------------------------- #
# Local tool + upstream executor scaffolding                                   #
# --------------------------------------------------------------------------- #


def _register_local_tool(
    tool_name: str,
    func: Callable[..., dict[str, Any]],
    *,
    credits_per_unit: float = TOOL_COST,
) -> None:
    get_service_registry().register_local(
        service_id=tool_name,
        name=f"Adversarial {tool_name}",
        description="Adversarial five-claims test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=func,
        credits_per_unit=credits_per_unit,
        unit_name="call",
    )


def _upstream_result(payload: dict[str, Any]) -> UpstreamMcpResult:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return UpstreamMcpResult(
        payload=payload,
        canonical_json=canonical,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        size_bytes=len(canonical.encode()),
        is_error=bool(payload.get("isError")),
    )


@dataclass
class AdversarialUpstream:
    """Minimal upstream executor that can die at a chosen boundary.

    Mirrors the production ``call_tool`` contract: ``before_dispatch`` is the
    durable checkpoint written immediately before the network send. Failing
    before calling it is provably non-delivered; failing after it is inherently
    ambiguous.
    """

    mode: str  # "success" | "delivery_uncertain" | "pre_dispatch_failure"
    dispatch_count: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Callable[[], Awaitable[None]],
    ) -> UpstreamMcpResult:
        self.calls.append({"arguments": arguments, "idempotency_key": idempotency_key})
        if self.mode == "pre_dispatch_failure":
            raise UpstreamMcpPreDispatchError("upstream_connection_failed")

        await before_dispatch()
        self.dispatch_count += 1
        if self.mode == "delivery_uncertain":
            raise UpstreamMcpDeliveryUncertainError()

        return _upstream_result(
            {"content": [{"type": "text", "text": "partner ok"}], "isError": False}
        )


def _register_upstream(tool_name: str, executor: AdversarialUpstream) -> None:
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Adversarial Upstream Tool",
        description="Controlled remote MCP test tool",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        credits_per_unit=TOOL_COST,
        upstream_tool_name="partner.echo",
        upstream_origin="https://partner.example",
    )


def _call_body(
    *,
    tool_name: str,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
    message: str = "hello",
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idempotency_key}",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": message},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


async def _ledger_split(
    client: AsyncClient, wallet_id: str, headers: dict[str, str], tool_name: str
) -> tuple[int, int]:
    """Return (debit_count, refund_count) for the given tool on the wallet."""
    resp = await client.get(f"/v1/billing/ledger/{wallet_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    entries = [
        entry
        for entry in resp.json()["entries"]
        if entry["service_category"] == "agent_comms"
        and tool_name in entry.get("description", "")
    ]
    debits = sum(1 for e in entries if e.get("action") == "debit")
    refunds = sum(1 for e in entries if e.get("action") == "refund")
    return debits, refunds


async def _spent_credits(permit_id: str) -> Decimal:
    permit = await get_permit_service().get_permit(permit_id)
    assert permit is not None
    return Decimal(str(permit.spent_credits))


# --------------------------------------------------------------------------- #
# Claim 1 — Charge-once under retry                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_claim1_replayed_key_executes_once_and_charges_once(
    client: AsyncClient, clean_database: None
) -> None:
    """A deliberate retry cannot double-execute or double-charge.

    The tool body increments a counter, so the assertion proves the *side
    effect* ran exactly once — not merely that the ledger shows one debit.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim1-echo"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    _register_local_tool(tool_name, echo)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="adv-claim1-permit",
        )
        body = _call_body(
            tool_name=tool_name,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="adv-claim1-invoke",
        )

        first = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )
        assert first.status_code == 200, first.text
        receipt = first.json()["result"]["receipt"]
        assert receipt["outcome"] == "success"

        # Hammer the same key twice more.
        for _ in range(2):
            replay = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )
            assert replay.status_code == 200
            assert (
                replay.json()["result"]["receipt"]["receipt_id"]
                == receipt["receipt_id"]
            )

        assert runs["count"] == 1, "the tool side effect ran more than once"
        debits, _ = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert debits == 1
        assert await _spent_credits(permit["permit_id"]) == Decimal(str(TOOL_COST))
    finally:
        get_service_registry().unregister_local(tool_name)


# --------------------------------------------------------------------------- #
# Claim 2 — Budget over-spend containment  [credential-only]                   #
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_claim2_permit_cap_below_call_cost_is_denied_before_any_charge(
    client: AsyncClient, clean_database: None
) -> None:
    """A permit whose cap is below the per-call cost never moves money."""
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim2-floor"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    _register_local_tool(tool_name, echo)
    try:
        # Cost is 2 credits/call; cap the permit at 1.
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            max_credits=1,
            idem_key="adv-claim2-floor-permit",
        )
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="adv-claim2-floor-invoke",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["error"]["message"] == "permit_budget_exceeded"

        assert runs["count"] == 0, "the tool ran despite an over-budget denial"
        debits, refunds = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert (debits, refunds) == (0, 0)
        assert await _spent_credits(permit["permit_id"]) == Decimal("0")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_claim2_cumulative_spend_cannot_exceed_the_permit_cap(
    client: AsyncClient, clean_database: None
) -> None:
    """Over-spend containment holds across a *sequence*, not just one call.

    This is the case the live HTTP battery cannot reach: it needs a seeded
    permit with a known cap and a tool with a known per-call cost. Cap = 5,
    cost = 2: two calls land (spent 2, then 4); the third would reach 6 and is
    denied. Distinct idempotency keys make each call a genuine new charge.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim2-cumulative"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    _register_local_tool(tool_name, echo)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            max_credits=5,
            idem_key="adv-claim2-cumulative-permit",
        )

        async def invoke(idem: str) -> dict[str, Any]:
            resp = await client.post(
                "/mcp/messages",
                json=_call_body(
                    tool_name=tool_name,
                    wallet_id=provisioned["agent_wallet_id"],
                    permit_id=permit["permit_id"],
                    idempotency_key=idem,
                ),
                headers=provisioned["agent_headers"],
            )
            assert resp.status_code == 200, resp.text
            return resp.json()

        first = await invoke("adv-claim2-cumulative-1")
        assert first["result"]["receipt"]["outcome"] == "success"
        assert await _spent_credits(permit["permit_id"]) == Decimal("2")

        second = await invoke("adv-claim2-cumulative-2")
        assert second["result"]["receipt"]["outcome"] == "success"
        assert await _spent_credits(permit["permit_id"]) == Decimal("4")

        # Third call would bring spend to 6 > cap 5.
        third = await invoke("adv-claim2-cumulative-3")
        assert third["error"]["message"] == "permit_budget_exceeded"

        # The denial did not run the tool, did not debit, and left spend at 4.
        assert runs["count"] == 2
        assert await _spent_credits(permit["permit_id"]) == Decimal("4")
        debits, refunds = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert (debits, refunds) == (2, 0)

        # Replaying the denied key stays denied and still moves nothing.
        replay = await invoke("adv-claim2-cumulative-3")
        assert replay["error"]["message"] == "permit_budget_exceeded"
        assert runs["count"] == 2
        debits_after, _ = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert debits_after == 2
    finally:
        get_service_registry().unregister_local(tool_name)


# --------------------------------------------------------------------------- #
# Claim 3 — Interrupted-invocation accounting  [credential-only]              #
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_claim3_induced_timeout_stays_charged_and_never_redispatches(
    client: AsyncClient, clean_database: None
) -> None:
    """A death after the dispatch checkpoint is charged, and a retry cannot
    turn it into a second dispatch, a refund, or a free call.

    This is the incentive attack in ``docs/failure-semantics.md``: an ambiguous
    call that auto-refunded would pay callers to induce timeouts against
    providers whose side effects completed. The charge stands; replay returns
    the identical signed ``delivery_uncertain`` receipt without redispatching.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim3-uncertain"
    executor = AdversarialUpstream("delivery_uncertain")
    _register_upstream(tool_name, executor)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="adv-claim3-uncertain-permit",
        )
        body = _call_body(
            tool_name=tool_name,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="adv-claim3-uncertain-invoke",
        )

        first = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )
        replay = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )

        error = first.json()["error"]
        assert error["code"] == -32005
        assert error["message"] == "delivery_uncertain"
        receipt = error["data"]["receipt"]
        assert receipt["outcome"] == "delivery_uncertain"
        assert Decimal(str(receipt["credits_charged"])) == Decimal("2")

        # Replay is byte-identical and did NOT redispatch.
        assert replay.json()["error"] == error
        assert executor.dispatch_count == 1
        assert len(executor.calls) == 1

        debits, refunds = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert (debits, refunds) == (1, 0), "uncertain delivery must stay charged"
        assert await _spent_credits(permit["permit_id"]) == Decimal("2")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_claim3_pre_dispatch_death_refunds_to_net_zero_without_executing(
    client: AsyncClient, clean_database: None
) -> None:
    """A death before the dispatch checkpoint refunds and never executes.

    The refund is durable (a refund ledger row correlated to the debit) and the
    signed receipt reports a net charge of zero. A retry cannot resurrect the
    call into a dispatch.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim3-predispatch"
    executor = AdversarialUpstream("pre_dispatch_failure")
    _register_upstream(tool_name, executor)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="adv-claim3-predispatch-permit",
        )
        body = _call_body(
            tool_name=tool_name,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="adv-claim3-predispatch-invoke",
        )

        first = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )
        replay = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )

        error = first.json()["error"]
        assert error["message"] == "upstream_pre_dispatch_failed"
        receipt = error["data"]["receipt"]
        assert receipt["outcome"] == "failed_refunded"
        assert Decimal(str(receipt["credits_charged"])) == Decimal("0")

        # Replay is identical and still never dispatched.
        assert replay.json()["error"] == error
        assert executor.dispatch_count == 0

        # Debit and its refund both landed; the net effect on spend is zero.
        debits, refunds = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert (debits, refunds) == (1, 1), "a refunded failure needs both rows"
        assert await _spent_credits(permit["permit_id"]) == Decimal("0")
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_claim3_conflicting_payload_under_a_spent_key_never_redispatches(
    client: AsyncClient, clean_database: None
) -> None:
    """An attacker cannot smuggle a second, different side effect under a key
    that already terminated. A reused key with a changed payload fails closed.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim3-conflict"
    executor = AdversarialUpstream("success")
    _register_upstream(tool_name, executor)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="adv-claim3-conflict-permit",
        )
        key = "adv-claim3-conflict-invoke"
        first = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key=key,
                message="first",
            ),
            headers=provisioned["agent_headers"],
        )
        conflict = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key=key,
                message="changed",
            ),
            headers=provisioned["agent_headers"],
        )

        assert "result" in first.json()
        assert conflict.json()["error"]["message"] == "idempotency_key_reused"
        assert executor.dispatch_count == 1
        assert len(executor.calls) == 1
        debits, _ = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            tool_name,
        )
        assert debits == 1
    finally:
        get_service_registry().unregister_local(tool_name)


# --------------------------------------------------------------------------- #
# Claim 4 — Signed, offline-verifiable receipts                               #
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_claim4_receipt_verifies_offline_and_tampering_is_caught(
    client: AsyncClient, clean_database: None
) -> None:
    """A stranger holding the exported receipt and the public key document can
    reach the same verdict this plane would — and a single flipped byte flips
    the verdict to tampered, while a missing key is reported as such, not as a
    forgery.
    """
    provisioned = await provision_agent_wallet(client)
    tool_name = "adv-claim4-echo"
    _register_local_tool(tool_name, lambda message="ok": {"message": message})
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="adv-claim4-permit",
        )
        invoke = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="adv-claim4-invoke",
            ),
            headers=provisioned["agent_headers"],
        )
        assert invoke.status_code == 200, invoke.text
        receipt_id = invoke.json()["result"]["receipt"]["receipt_id"]

        # The receipt owner exports; the key document is fetched unauthenticated.
        bundle_resp = await client.get(
            f"/v1/receipts/{receipt_id}/portable",
            headers=provisioned["agent_headers"],
        )
        assert bundle_resp.status_code == 200, bundle_resp.text
        keys_resp = await client.get("/.well-known/trust-keys.json")
        assert keys_resp.status_code == 200, keys_resp.text
        bundle = bundle_resp.json()
        key_set = key_set_from_document(keys_resp.json())

        genuine = verify_bundle(bundle, key_set)
        assert genuine.ok, genuine.reason
        assert genuine.status is VerificationStatus.VERIFIED
        assert genuine.receipt_id == receipt_id
        assert genuine.claims["outcome"] == "success"

        # Flip a signed field: the signature no longer covers the bytes.
        payload = json.loads(bundle["signing_input"])
        payload["credits_charged"] = "0.01"
        forged = dict(bundle)
        forged["signing_input"] = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        tampered = verify_bundle(forged, key_set)
        assert not tampered.ok
        assert tampered.is_tampered
        assert tampered.status is VerificationStatus.INVALID

        # No key for this kid is "cannot tell", not "forged".
        missing = verify_bundle(bundle, {})
        assert missing.status is VerificationStatus.UNKNOWN_KEY
        assert not missing.is_tampered
    finally:
        get_service_registry().unregister_local(tool_name)


# --------------------------------------------------------------------------- #
# Claim 5 — Authority-before-money denial                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_claim5_out_of_scope_denial_is_signed_and_moves_no_money(
    client: AsyncClient, clean_database: None
) -> None:
    """A call for a tool the permit does not allow is denied before money
    moves, with a signed denial receipt that carries no ledger linkage. The
    full denial matrix is ``scripts/red_team_trust_plane.py``; this pins the
    load-bearing invariant in the pytest suite.
    """
    provisioned = await provision_agent_wallet(client)
    allowed_tool = "adv-claim5-allowed"
    blocked_tool = "adv-claim5-blocked"
    runs = {"blocked": 0}

    _register_local_tool(allowed_tool, lambda message="ok": {"message": message})

    def blocked(message: str = "ok") -> dict[str, Any]:
        runs["blocked"] += 1
        return {"should_not_run": True}

    _register_local_tool(blocked_tool, blocked)
    try:
        # Permit allows only allowed_tool.
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=allowed_tool,
            idem_key="adv-claim5-permit",
        )
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=blocked_tool,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="adv-claim5-invoke",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200, resp.text
        error = resp.json()["error"]
        assert error["message"] == "permit_tool_not_allowed"

        # A signed denial receipt with no ledger linkage.
        receipt = (error.get("data") or {}).get("receipt")
        assert receipt is not None, "out-of-scope denial produced no receipt"
        assert receipt["outcome"] == "denied"
        assert receipt.get("ledger_entry_id") is None

        assert runs["blocked"] == 0, "the blocked tool executed"
        debits, refunds = await _ledger_split(
            client, provisioned["agent_wallet_id"], provisioned["agent_headers"],
            blocked_tool,
        )
        assert (debits, refunds) == (0, 0)
        assert await _spent_credits(permit["permit_id"]) == Decimal("0")
    finally:
        get_service_registry().unregister_local(allowed_tool)
        get_service_registry().unregister_local(blocked_tool)
