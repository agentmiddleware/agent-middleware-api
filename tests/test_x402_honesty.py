"""x402 honesty pass: one approved sentence everywhere x402 appears.

GTM fix: every x402 surface, doc, and response must say x402 authorizes and
records but does not move money, using one approved sentence constant
(`X402_HONESTY_NOTE`). These tests pin the sentence literal, assert the SDK
copy matches the server copy, assert the OpenAPI tag and descriptions carry
it, assert both response bodies repeat it, and assert the two live docs quote
it. If any surface drifts into settlement language, one of these fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.x402_engine import X402_HONESTY_NOTE
from b2a_sdk import x402 as sdk_x402
from tests.test_trust_helpers import (
    create_tool_permit,
    provision_agent_wallet,
)

APPROVED_SENTENCE = (
    "x402 authorizes and records a payment demand but does not move money."
)

EVM_PAY_TO = "0x1111111111111111111111111111111111111111"
EVM_PAYER = "0x2222222222222222222222222222222222222222"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_honesty_sentence_literal_is_pinned():
    """The approved sentence wording itself, so edits are deliberate."""
    assert X402_HONESTY_NOTE == APPROVED_SENTENCE


def test_sdk_honesty_sentence_matches_server():
    """The SDK keeps its own copy for the offline path; it must be identical."""
    assert sdk_x402.X402_HONESTY_NOTE == X402_HONESTY_NOTE
    assert APPROVED_SENTENCE in (sdk_x402.__doc__ or "")


def test_openapi_x402_tag_and_descriptions_carry_sentence():
    """No x402 path may sit under a Settlement tag, and both endpoint
    descriptions must carry the approved sentence."""
    spec = app.openapi()
    for path in ("/v1/x402/parse", "/v1/x402/settle"):
        assert path in spec["paths"], f"{path} missing from OpenAPI"
        operation = spec["paths"][path]["post"]
        for tag in operation.get("tags", []):
            assert "settlement" not in tag.lower(), f"{path} tagged {tag!r}"
        assert APPROVED_SENTENCE in (operation.get("description") or "")


@pytest.mark.anyio
async def test_parse_response_body_carries_notice(client, clean_database):
    """The parse response repeats the sentence in its notice field."""
    from tests.test_trust_helpers import BOOTSTRAP_HEADERS

    resp = await client.post(
        "/v1/x402/parse",
        json={
            "status_code": 402,
            "headers": {
                "X-402-Amount": "1.50",
                "X-402-PayTo": EVM_PAY_TO,
                "X-402-Network": "base",
            },
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["notice"] == APPROVED_SENTENCE


@pytest.mark.anyio
async def test_settle_response_body_carries_notice(client, clean_database):
    """A live settle repeats the sentence in its notice field."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    permit = await create_tool_permit(
        client,
        wallet_id=wallet_id,
        key_id=provisioned["key_id"],
        tool_name="x402.payment",
        max_credits=100,
        idem_key="x402-honesty-permit",
    )
    resp = await client.post(
        "/v1/x402/settle",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": wallet_id,
            "amount": "0.03",
            "pay_to": EVM_PAY_TO,
            "network": "base",
            "payer": EVM_PAYER,
        },
        headers={**provisioned["agent_headers"], "Idempotency-Key": "x402-honesty-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["notice"] == APPROVED_SENTENCE


def test_live_docs_quote_approved_sentence():
    """settlement-rails.md and PRODUCT_STRATEGY.md quote the sentence verbatim."""
    root = Path(__file__).resolve().parent.parent
    for doc in ("docs/settlement-rails.md", "docs/PRODUCT_STRATEGY.md"):
        text = (root / doc).read_text()
        assert APPROVED_SENTENCE in text, f"{doc} missing approved sentence"
