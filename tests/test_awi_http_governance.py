"""AWI HTTP high-risk routes must require permit → meter → receipt."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, LedgerEntryModel
from app.main import app
from app.services.idempotency import MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)

RAG_QUERY_ENDPOINT = "POST /v1/awi/rag/query"
RAG_QUERY_PAYLOAD = {"query": "laptops", "top_k": 3}
HEADER_SOURCE = "Idempotency-Key header"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_rag_query_denied_without_permit(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    resp = await client.post(
        "/v1/awi/rag/query",
        json={"query": "laptops", "top_k": 3},
        headers={
            **provisioned["agent_headers"],
            "X-Wallet-Id": provisioned["agent_wallet_id"],
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "permit_required"


@pytest.mark.anyio
async def test_rag_query_succeeds_with_permit_and_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-http-rag",
    )
    resp = await client.post(
        "/v1/awi/rag/query",
        json={"query": "laptops", "top_k": 3},
        headers={
            **provisioned["agent_headers"],
            "X-Wallet-Id": provisioned["agent_wallet_id"],
            "X-Permit-Id": permit["permit_id"],
            "Idempotency-Key": "awi-http-rag-1",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "laptops"
    assert "results" in body
    assert body["receipt"]["permit_id"] == permit["permit_id"]
    assert body["receipt"]["outcome"] == "success"
    assert body["receipt"]["signature"]

    receipt_resp = await client.get(
        f"/v1/receipts/{body['receipt']['receipt_id']}",
        headers=provisioned["agent_headers"],
    )
    assert receipt_resp.status_code == 200, receipt_resp.text
    receipt = receipt_resp.json()
    assert Decimal(str(receipt["credits_authorized"])) == Decimal("3")
    assert Decimal(str(receipt["credits_charged"])) == Decimal("3")
    assert receipt["ledger_entry_id"]


@pytest.mark.anyio
async def test_rag_query_insufficient_funds_aborts_and_replays(client, clean_database):
    """402 closes the idempotency key; same key replays 402 (not 409 in-progress)."""
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-broke",
    )

    # Leave the agent with 2 credits (rag costs 3) after permit creation.
    transfer = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": provisioned["agent_wallet_id"],
            "to_wallet_id": provisioned["sponsor_wallet_id"],
            "amount": 998,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert transfer.status_code == 200, transfer.text

    headers = {
        **provisioned["agent_headers"],
        "X-Wallet-Id": provisioned["agent_wallet_id"],
        "X-Permit-Id": permit["permit_id"],
        "Idempotency-Key": "awi-http-broke-1",
    }
    payload = {"query": "laptops", "top_k": 3}

    first = await client.post("/v1/awi/rag/query", json=payload, headers=headers)
    assert first.status_code == 402, first.text
    assert first.json()["detail"]["error"] == "insufficient_funds"

    second = await client.post("/v1/awi/rag/query", json=payload, headers=headers)
    assert second.status_code == 402, second.text
    assert second.json()["detail"]["error"] == "insufficient_funds"


@pytest.mark.anyio
async def test_execute_denied_without_wallet_scoped_session(client, clean_database):
    """Sessions without wallet_id cannot enter the governed execute path."""
    create = await client.post(
        "/v1/awi/sessions",
        json={"target_url": "https://example.com"},
        headers={"X-API-Key": "test-key"},
    )
    assert create.status_code == 201
    session_id = create.json()["session_id"]

    resp = await client.post(
        "/v1/awi/execute",
        json={
            "session_id": session_id,
            "action": "navigate_to",
            "parameters": {"url": "https://example.com/next"},
        },
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "wallet_required"


@pytest.mark.anyio
async def test_awi_route_keys_its_debit_to_the_idempotency_record(
    client, clean_database
):
    """The governed AWI route must key its debit to the request's identity.

    This path used to call ``money.charge()`` with no ``operation_key``, so it
    had neither the ``uq_ledger_wallet_operation_key`` constraint nor the
    adopt-the-existing-debit recovery the governed MCP path relies on. A charge
    that committed but whose acknowledgement was lost took the failure branch,
    which releases the permit budget and *completes* the idempotency record as
    ``charge_failed`` -- so the caller retried under a fresh key and paid twice
    for one logical action.

    Asserted on the real route rather than on ``money.charge`` directly,
    because the defect was the wiring: the mechanism already existed and this
    caller simply did not use it.
    """
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-opkey",
    )
    resp = await client.post(
        "/v1/awi/rag/query",
        json={"query": "laptops", "top_k": 3},
        headers={
            **provisioned["agent_headers"],
            "X-Wallet-Id": provisioned["agent_wallet_id"],
            "X-Permit-Id": permit["permit_id"],
            "Idempotency-Key": "awi-opkey-1",
        },
    )
    assert resp.status_code == 200, resp.text

    factory = get_session_factory()
    async with factory() as session:
        record_id = (
            await session.execute(
                select(IdempotencyRecordModel.record_id).where(
                    IdempotencyRecordModel.wallet_id == provisioned["agent_wallet_id"],
                    IdempotencyRecordModel.idempotency_key == "awi-opkey-1",
                )
            )
        ).scalar_one()
        keyed = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(LedgerEntryModel.operation_key == record_id)
            )
        ).scalar_one()
        unkeyed = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(
                    LedgerEntryModel.wallet_id == provisioned["agent_wallet_id"],
                    LedgerEntryModel.action == "charge",
                    LedgerEntryModel.operation_key.is_(None),
                )
            )
        ).scalar_one()

    assert keyed == 1, (
        "the AWI debit is not keyed to its idempotency record, so a retry "
        "after a lost acknowledgement would debit again"
    )
    assert unkeyed == 0, "a governed AWI charge landed with no operation_key"


# ── Client idempotency-key contract ──────────────────────────────────────────
# The governed AWI routes hold the ``Idempotency-Key`` header to the same
# contract as the MCP surfaces (``app.services.idempotency``): every line the
# client sent is validated, never coerced, must agree with every other line,
# and is stored verbatim as the replay identity.


async def _provision_rag_caller(
    client: AsyncClient, *, permit_idem_key: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """A funded agent wallet plus an ``awi_rag_query`` permit.

    Returns the provisioned wallet and the governed headers *without* an
    ``Idempotency-Key`` so each test supplies exactly the value under test.
    """
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key=permit_idem_key,
    )
    headers = {
        **provisioned["agent_headers"],
        "X-Wallet-Id": provisioned["agent_wallet_id"],
        "X-Permit-Id": permit["permit_id"],
    }
    return provisioned, headers


async def _rag_query_state(wallet_id: str) -> tuple[list[str], int]:
    """(stored replay identities for the rag route, wallet debit count).

    A debit is a negative ledger amount -- the invariant the ledger model
    states and the reconciler relies on -- rather than an action label.
    """
    factory = get_session_factory()
    async with factory() as session:
        keys = (
            (
                await session.execute(
                    select(IdempotencyRecordModel.idempotency_key).where(
                        IdempotencyRecordModel.wallet_id == wallet_id,
                        IdempotencyRecordModel.endpoint == RAG_QUERY_ENDPOINT,
                    )
                )
            )
            .scalars()
            .all()
        )
        debits = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(
                    LedgerEntryModel.wallet_id == wallet_id,
                    LedgerEntryModel.amount < 0,
                )
            )
        ).scalar_one()
    return sorted(keys), debits


def _assert_invalid_key(detail: dict[str, Any], *, reason_code: str) -> None:
    assert detail["error"] == "invalid_idempotency_key"
    assert detail["reason_code"] == reason_code
    assert HEADER_SOURCE in detail["source"]
    assert detail["message"].startswith("invalid_idempotency_key")
    assert detail["remediation"]["type"] == "retry_with_valid_idempotency_key"
    assert detail["tool"] == "awi_rag_query"
    assert "receipt" not in detail


@pytest.mark.anyio
async def test_absent_idempotency_key_is_required(client, clean_database):
    """No header at all keeps the route's own ``idempotency_key_required``."""
    provisioned, headers = await _provision_rag_caller(
        client, permit_idem_key="permit-awi-key-absent"
    )
    resp = await client.post(
        "/v1/awi/rag/query", json=RAG_QUERY_PAYLOAD, headers=headers
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "idempotency_key_required"
    assert detail["tool"] == "awi_rag_query"
    assert await _rag_query_state(provisioned["agent_wallet_id"]) == ([], 0)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("header_value", "reason_code"),
    [
        ("", "idempotency_key_blank"),
        ("   ", "idempotency_key_blank"),
        ("x" * (MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH + 1), "idempotency_key_too_long"),
        ("awi\x00key", "idempotency_key_control_characters"),
        ("awi\x7fkey", "idempotency_key_control_characters"),
    ],
)
async def test_malformed_idempotency_key_is_refused_before_any_effect(
    client, clean_database, header_value, reason_code
):
    """A present-but-unusable key is refused under the shared contract.

    ``begin_awi_http_governed`` used to accept any non-blank header as-is: it
    applied no length cap, so a key wider than the 128-character store column
    passed permit validation and reached the database, and it never checked
    for control characters. Two identical retries must both be refused with
    the machine-actionable payload the MCP surfaces return, and with nothing
    written and nothing charged.
    """
    provisioned, headers = await _provision_rag_caller(
        client, permit_idem_key="permit-awi-key-bad"
    )
    headers["Idempotency-Key"] = header_value

    for _ in range(2):
        resp = await client.post(
            "/v1/awi/rag/query", json=RAG_QUERY_PAYLOAD, headers=headers
        )
        assert resp.status_code == 400, resp.text
        _assert_invalid_key(resp.json()["detail"], reason_code=reason_code)

    assert await _rag_query_state(provisioned["agent_wallet_id"]) == ([], 0)


@pytest.mark.anyio
async def test_conflicting_idempotency_key_lines_are_refused(client, clean_database):
    """Two header lines naming different keys is an ambiguity, refused as on MCP.

    The handlers used to read the key through a single-value ``Header``
    parameter, which surfaces only the first line, so a second line carrying
    a different key was never seen: the first key silently chose the replay
    identity and the action ran and was charged. Identical repeated lines
    collapse to one key and still work.
    """
    provisioned, headers = await _provision_rag_caller(
        client, permit_idem_key="permit-awi-key-dup"
    )
    conflicting = [
        *headers.items(),
        ("Idempotency-Key", "awi-dup-a"),
        ("Idempotency-Key", "awi-dup-b"),
    ]
    for _ in range(2):
        resp = await client.post(
            "/v1/awi/rag/query", json=RAG_QUERY_PAYLOAD, headers=conflicting
        )
        assert resp.status_code == 400, resp.text
        _assert_invalid_key(
            resp.json()["detail"], reason_code="idempotency_key_conflict"
        )
    assert await _rag_query_state(provisioned["agent_wallet_id"]) == ([], 0)

    repeated = [
        *headers.items(),
        ("Idempotency-Key", "awi-dup-same"),
        ("Idempotency-Key", "awi-dup-same"),
    ]
    resp = await client.post(
        "/v1/awi/rag/query", json=RAG_QUERY_PAYLOAD, headers=repeated
    )
    assert resp.status_code == 200, resp.text
    assert await _rag_query_state(provisioned["agent_wallet_id"]) == (
        ["awi-dup-same"],
        1,
    )


@pytest.mark.anyio
async def test_padded_idempotency_key_is_a_distinct_identity(client, clean_database):
    """The key is stored exactly as sent: ``' k'`` and ``'k'`` are two records.

    The old code stored ``idempotency_key.strip()``, so the two collapsed into
    one replay identity and the second call replayed the first receipt instead
    of running. Stripping was dropped deliberately: the Python SDK trims
    client-side before sending and no first-party caller sends a padded key,
    so the only server-side effect was to merge distinct client keys. The MCP
    surfaces store verbatim; the AWI routes now do the same.
    """
    provisioned, headers = await _provision_rag_caller(
        client, permit_idem_key="permit-awi-key-pad"
    )
    padded = await client.post(
        "/v1/awi/rag/query",
        json=RAG_QUERY_PAYLOAD,
        headers={**headers, "Idempotency-Key": " awi-pad-1"},
    )
    bare = await client.post(
        "/v1/awi/rag/query",
        json=RAG_QUERY_PAYLOAD,
        headers={**headers, "Idempotency-Key": "awi-pad-1"},
    )
    assert padded.status_code == 200, padded.text
    assert bare.status_code == 200, bare.text
    assert (
        padded.json()["receipt"]["receipt_id"] != bare.json()["receipt"]["receipt_id"]
    )
    assert await _rag_query_state(provisioned["agent_wallet_id"]) == (
        [" awi-pad-1", "awi-pad-1"],
        2,
    )


@pytest.mark.anyio
async def test_valid_idempotency_key_at_store_width_replays_same_receipt(
    client, clean_database
):
    """Positive control: a usable key -- here exactly the store width -- replays."""
    provisioned, headers = await _provision_rag_caller(
        client, permit_idem_key="permit-awi-key-ok"
    )
    key = "k" * MAX_CLIENT_IDEMPOTENCY_KEY_LENGTH
    headers["Idempotency-Key"] = key

    first = await client.post(
        "/v1/awi/rag/query", json=RAG_QUERY_PAYLOAD, headers=headers
    )
    second = await client.post(
        "/v1/awi/rag/query", json=RAG_QUERY_PAYLOAD, headers=headers
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert (
        first.json()["receipt"]["receipt_id"] == second.json()["receipt"]["receipt_id"]
    )
    assert (
        first.json()["receipt"]["ledger_entry_id"]
        == second.json()["receipt"]["ledger_entry_id"]
    )
    assert await _rag_query_state(provisioned["agent_wallet_id"]) == ([key], 1)
