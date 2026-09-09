"""Where an audit-chain loss is retryable, and the one place it must not be.

``append_chained_audit_event`` retries a contended per-wallet chain head 64
times and then raises ``AuditChainContendedError``. What that should mean to
the caller depends entirely on whether the call had already run.

A refusal that ran nothing -- a permit denial, a lost quote -- can say "retry":
no tool executed and no wallet moved, so a second attempt costs nothing and the
first left no terminal record behind. That is the retryable ``-32005`` answer.

Every audit write past the charge is the opposite, and is the reason this file
exists. It audits *after* the tool ran and the wallet was charged, so "retry"
would invite a second execution of a call the caller already paid for. Nor can
it be softened into a success: ``create_receipt`` takes
``audit_event_id=audit_event.event_id``, so no audit event means no signed
receipt either, and ``reconcile_stuck_records`` repairs a stuck record only when
a receipt exists -- without one it counts the record for manual review instead.
The honest answer there is the unclassified failure it has always been.

Finalization is only the most obvious of those sites. The local
refund-succeeded path and the upstream post-charge helpers audit after
execution too, and guarding finalize alone left both free to hand a caller who
had already run and paid a "retry" -- so each is pinned separately below rather
than trusted to a shared reading of the control flow.

The retryable half carries its own obligation, tested here too: the -32005 has
to name a retry the caller can actually make. A governed call has an
idempotency record open by the time these refusals happen, and reconciliation
deliberately does not delete uncharged local records, so a record left in
progress would meet every retry of that key with ``idempotency_in_progress``
forever.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.billing import ServiceCategory
from app.services import audit_chain
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import UpstreamMcpResult
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL_COST = 2.0


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def audited_tool():
    tool_name = "audit-contention-echo"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name="Audit contention echo",
        description="Audit-chain contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        yield tool_name, runs
    finally:
        get_service_registry().unregister_local(tool_name)


def _call_body(
    *, tool_name: str, wallet_id: str, permit_id: str, idempotency_key: str
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idempotency_key}",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": "hello"},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


def _always_contended(monkeypatch) -> None:
    """Make every chain-head append lose, deterministically.

    Patched at ``_sign_with_previous`` rather than raced: a test that waits for
    real contention passes on a fast machine for the wrong reason.
    """

    def _lost(*args: Any, **kwargs: Any) -> None:
        raise audit_chain._HeadConflict()

    monkeypatch.setattr(audit_chain, "_sign_with_previous", _lost)


@pytest.mark.anyio
async def test_a_refusal_that_ran_nothing_answers_audit_contention_as_retryable(
    client: AsyncClient, clean_database: None, audited_tool, monkeypatch
) -> None:
    """A denial whose audit write loses the chain head is safe to retry.

    The permit is not valid for this tool, so the call is refused before
    anything runs. Writing that denial to the audit chain is what fails here,
    and because nothing executed the caller can simply try again -- which is
    what -32005 says. Before this it landed as an unclassified internal_error.
    """
    tool_name, runs = audited_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name="some-other-tool",
        idem_key="audit-contention-permit-1",
    )

    _always_contended(monkeypatch)
    resp = await client.post(
        "/mcp/messages",
        json=_call_body(
            tool_name=tool_name,
            wallet_id=ctx["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="audit-contention-denied-1",
        ),
        headers=ctx["agent_headers"],
    )
    monkeypatch.undo()

    assert resp.status_code == 200, resp.text
    error = resp.json()["error"]
    assert error["message"] != "internal_error", error
    assert error["code"] == -32005, error
    # The tool never ran, which is what makes the retryable answer honest.
    assert runs["count"] == 0

    # Now take the retry that -32005 promised, on the same key. Asserting the
    # code alone proved the classification and nothing about the promise: the
    # governed record opened before this denial was left in progress, so the
    # retry came back idempotency_in_progress and no retry of that key could
    # ever have made progress again.
    again = await client.post(
        "/mcp/messages",
        json=_call_body(
            tool_name=tool_name,
            wallet_id=ctx["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="audit-contention-denied-1",
        ),
        headers=ctx["agent_headers"],
    )
    assert again.status_code == 200, again.text
    retry_error = again.json()["error"]
    assert retry_error["message"] != "idempotency_in_progress", retry_error
    # It reaches the real answer instead: the permit does not cover this tool.
    assert retry_error["code"] != -32005, retry_error
    assert runs["count"] == 0


@pytest.mark.anyio
async def test_finalization_never_tells_a_charged_caller_to_retry(
    client: AsyncClient, clean_database: None, audited_tool, monkeypatch
) -> None:
    """The call ran and was charged, so its audit loss stays non-retryable.

    This is the guard on the classification above. Finalization writes its
    audit event after execution, so answering -32005 there would invite a
    second run of a call the caller already paid for, and reporting success
    would hand back a charged call with no receipt -- the receipt is built from
    the audit event's id -- and a record reconciliation can only flag for
    manual review. It keeps failing unclassified, deliberately.
    """
    tool_name, runs = audited_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        max_credits=10,
        idem_key="audit-contention-permit-2",
    )

    real_sign = audit_chain._sign_with_previous
    state = {"executed": False}

    def _lose_only_after_the_tool_ran(*args: Any, **kwargs: Any) -> None:
        # Pre-charge audits still succeed; only the post-execution finalize
        # write loses, which is the case under test.
        if state["executed"]:
            raise audit_chain._HeadConflict()
        return real_sign(*args, **kwargs)

    def echo_then_arm(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        state["executed"] = True
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name="Audit contention echo",
        description="Audit-chain contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo_then_arm,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    monkeypatch.setattr(
        audit_chain, "_sign_with_previous", _lose_only_after_the_tool_ran
    )

    resp = await client.post(
        "/mcp/messages",
        json=_call_body(
            tool_name=tool_name,
            wallet_id=ctx["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="audit-contention-charged-1",
        ),
        headers=ctx["agent_headers"],
    )
    monkeypatch.undo()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "error" in body, body
    # Never the retryable code: the tool ran once and the wallet was charged.
    assert body["error"]["code"] != -32005, body
    assert runs["count"] == 1


@pytest.mark.anyio
async def test_a_local_call_that_ran_and_refunded_is_never_told_to_retry(
    client: AsyncClient, clean_database: None, monkeypatch
) -> None:
    """The refund-succeeded path audits after execution, so it is not retryable.

    A local tool that performs its side effect and then raises is refunded, its
    permit budget released, and the failure audited -- and that audit write sits
    outside the finalize loop. Guarding finalize alone therefore left this path
    answering -32005 for a call that had already run. With legacy unpermitted
    MCP there is no durable idempotency record behind that answer, so the retry
    it invites simply runs the side effect a second time.
    """
    tool_name = "audit-contention-sideeffect"
    runs = {"count": 0}

    def explode_after_running(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        raise RuntimeError("tool_failed_after_side_effect")

    get_service_registry().register_local(
        service_id=tool_name,
        name="Audit contention side effect",
        description="Audit-chain contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=explode_after_running,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        ctx = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=ctx["agent_wallet_id"],
            key_id=ctx["key_id"],
            tool_name=tool_name,
            max_credits=10,
            idem_key="audit-contention-permit-3",
        )

        real_sign = audit_chain._sign_with_previous

        def _lose_only_after_the_tool_ran(*args: Any, **kwargs: Any) -> None:
            if runs["count"]:
                raise audit_chain._HeadConflict()
            return real_sign(*args, **kwargs)

        monkeypatch.setattr(
            audit_chain, "_sign_with_previous", _lose_only_after_the_tool_ran
        )
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=ctx["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="audit-contention-sideeffect-1",
            ),
            headers=ctx["agent_headers"],
        )
        monkeypatch.undo()
    finally:
        get_service_registry().unregister_local(tool_name)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "error" in body, body
    assert body["error"]["code"] != -32005, body
    assert runs["count"] == 1


@pytest.mark.anyio
async def test_a_charged_upstream_call_is_never_told_to_retry(
    client: AsyncClient, clean_database: None, monkeypatch
) -> None:
    """The upstream success audit runs after dispatch and charge, so not retryable.

    ``_execute_upstream_after_charge`` and its two failure helpers write their
    audit events once the partner has been called and the wallet debited. They
    are a separate code path from finalize, and guarding finalize alone left
    them answering -32005 for a call the partner had already executed -- the
    one outcome the gateway's at-most-one-dispatch promise cannot survive.
    """
    tool_name = "audit-contention-upstream"
    dispatches = {"count": 0}

    class _CountingUpstream:
        async def call_tool(
            self,
            arguments: dict[str, Any],
            *,
            invocation_id: str,
            idempotency_key: str,
            before_dispatch: Any,
        ) -> UpstreamMcpResult:
            await before_dispatch()
            dispatches["count"] += 1
            payload = {"content": [{"type": "text", "text": "partner ok"}]}
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            return UpstreamMcpResult(
                payload=payload,
                canonical_json=canonical,
                response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
                size_bytes=len(canonical.encode()),
                is_error=False,
            )

    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Audit contention upstream",
        description="Audit-chain contention surface test tool",
        category=ServiceCategory.AGENT_COMMS,
        executor=_CountingUpstream(),
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        credits_per_unit=TOOL_COST,
        upstream_tool_name="partner.echo",
        upstream_origin="https://partner.example",
    )
    try:
        ctx = await provision_agent_wallet(client)
        permit = await create_tool_permit(
            client,
            wallet_id=ctx["agent_wallet_id"],
            key_id=ctx["key_id"],
            tool_name=tool_name,
            max_credits=10,
            idem_key="audit-contention-permit-4",
        )

        real_sign = audit_chain._sign_with_previous

        def _lose_only_after_dispatch(*args: Any, **kwargs: Any) -> None:
            if dispatches["count"]:
                raise audit_chain._HeadConflict()
            return real_sign(*args, **kwargs)

        monkeypatch.setattr(
            audit_chain, "_sign_with_previous", _lose_only_after_dispatch
        )
        resp = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=ctx["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="audit-contention-upstream-1",
            ),
            headers=ctx["agent_headers"],
        )
        monkeypatch.undo()
    finally:
        get_service_registry().unregister_local(tool_name)

    assert resp.status_code == 200, resp.text
    # The partner ran exactly once; nothing may invite a second send.
    assert dispatches["count"] == 1
    body = resp.json()
    if "error" in body:
        assert body["error"]["code"] != -32005, body
