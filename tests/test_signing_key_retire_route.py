from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import SigningKeyModel
from app.main import app
from app.services.signing_keys import get_signing_key_service
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _insert_superseded_key(key_id: str = "test-old-kid") -> SigningKeyModel:
    """Insert a superseded key row as a redeploy rotation would leave it."""

    factory = get_session_factory()
    async with factory() as session:
        key = SigningKeyModel(
            key_id=key_id,
            public_key_b64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            status="active",
        )
        session.add(key)
        await session.commit()
        await session.refresh(key)
        return key


@pytest.mark.anyio
async def test_retire_superseded_key_marks_retired_and_stays_queryable(
    client,
    clean_database,
):
    await get_signing_key_service().get_active_key()
    await _insert_superseded_key()

    resp = await client.post(
        "/v1/signing-keys/test-old-kid/retire", headers=BOOTSTRAP_HEADERS
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["key_id"] == "test-old-kid"
    assert body["status"] == "retired"
    assert body["retired_at"] is not None
    assert "private_key" not in body

    # Retired metadata stays queryable so old receipts keep verifying.
    fetched = await client.get(
        "/v1/signing-keys/test-old-kid", headers=BOOTSTRAP_HEADERS
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "retired"


@pytest.mark.anyio
async def test_retire_unknown_key_returns_not_found(client, clean_database):
    resp = await client.post(
        "/v1/signing-keys/no-such-kid/retire", headers=BOOTSTRAP_HEADERS
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "signing_key_not_found"


@pytest.mark.anyio
async def test_retire_active_key_is_refused(client, clean_database):
    active = await get_signing_key_service().get_active_key()

    resp = await client.post(
        f"/v1/signing-keys/{active.key_id}/retire", headers=BOOTSTRAP_HEADERS
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "signing_key_is_active"

    # The active key is untouched: still active, still signing.
    fetched = await client.get(
        f"/v1/signing-keys/{active.key_id}", headers=BOOTSTRAP_HEADERS
    )
    assert fetched.json()["status"] == "active"


@pytest.mark.anyio
async def test_retire_requires_bootstrap_admin(client, clean_database):
    await get_signing_key_service().get_active_key()
    await _insert_superseded_key()
    wallet = await provision_agent_wallet(client)

    denied = await client.post(
        "/v1/signing-keys/test-old-kid/retire",
        headers=wallet["agent_headers"],
    )
    assert denied.status_code == 403

    unauthenticated = await client.post("/v1/signing-keys/test-old-kid/retire")
    assert unauthenticated.status_code in (401, 403)

    # The refused calls changed nothing.
    fetched = await client.get(
        "/v1/signing-keys/test-old-kid", headers=BOOTSTRAP_HEADERS
    )
    assert fetched.json()["status"] == "active"
