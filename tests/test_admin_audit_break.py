"""Break-it regressions: admin-gated routes and the audit router.

Covers calling admin routes with no credentials, with a plain wallet key,
and with a JWT carrying caller-chosen admin-like scopes; cross-wallet reads
(IDOR) on audit events, audit summary, chain verification, and key rotation
logs; mass assignment on policy update bodies; malformed-input handling;
and concurrent rotation of one key.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.audit_log import record_audit_event


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


ADMIN = {"X-API-Key": "test-key"}

# Key-rotation audit logs when the fix was written; the route now validates
# limit the same way the audit list does.
_LOGS_LIMIT_MAX = 200


async def _sponsor(client: AsyncClient, name: str) -> str:
    r = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": name,
            "email": f"{name}@example.com",
            "initial_credits": 10000,
            "require_kyc": False,
        },
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    return r.json()["wallet_id"]


async def _agent(client: AsyncClient, sponsor_id: str, agent_id: str) -> str:
    r = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_id,
            "agent_id": agent_id,
            "budget_credits": 1000,
        },
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    return r.json()["wallet_id"]


async def _wallet_key(
    client: AsyncClient, wallet_id: str, name: str = "k"
) -> tuple[str, str]:
    r = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": name},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["api_key"], body["key_id"]


@pytest.mark.anyio
async def test_admin_and_audit_routes_refuse_anonymous(client, clean_database):
    targets = [
        ("GET", "/v1/audit/events", None),
        ("GET", "/v1/audit/summary", None),
        ("POST", "/v1/audit/verify-chain", {}),
        ("GET", "/v1/policies", None),
        ("POST", "/v1/policies", {"wallet_id": "w", "name": "n"}),
        ("GET", "/v1/policies/x", None),
        ("PATCH", "/v1/policies/x", {"name": "n"}),
        (
            "POST",
            "/v1/billing/wallets/sponsor",
            {"sponsor_name": "s", "email": "s@e.com"},
        ),
        ("POST", "/v1/receipts/verify", {"receipt_id": "nope"}),
        ("POST", "/v1/receipts/reconciliation/refunds/nope/retry", None),
    ]
    for method, path, body in targets:
        if method == "GET":
            r = await client.get(path)
        elif method == "PATCH":
            r = await client.patch(path, json=body)
        else:
            r = await client.post(path, json=body)
        assert r.status_code in (401, 403), (method, path, r.status_code)


@pytest.mark.anyio
async def test_wallet_key_cannot_reach_admin_routes(client, clean_database):
    sp = await _sponsor(client, "brk-adm")
    w = await _agent(client, sp, "brk-adm-a")
    key, _ = await _wallet_key(client, w)
    headers = {"X-API-Key": key}
    targets = [
        ("GET", "/v1/policies", None),
        ("POST", "/v1/policies", {"wallet_id": w, "name": "n"}),
        ("GET", "/v1/policies/some-id", None),
        ("PATCH", "/v1/policies/some-id", {"name": "n"}),
        (
            "POST",
            "/v1/billing/wallets/sponsor",
            {"sponsor_name": "s", "email": "s@e.com"},
        ),
        ("POST", "/v1/receipts/verify", {"receipt_id": "nope"}),
        ("POST", "/v1/receipts/reconciliation/refunds/nope/retry", None),
    ]
    for method, path, body in targets:
        if method == "GET":
            r = await client.get(path, headers=headers)
        elif method == "PATCH":
            r = await client.patch(path, json=body, headers=headers)
        else:
            r = await client.post(path, json=body, headers=headers)
        assert r.status_code == 403, (method, path, r.status_code, r.text)


@pytest.mark.anyio
async def test_wallet_key_audit_reads_stay_in_wallet(client, clean_database):
    sp = await _sponsor(client, "brk-idor")
    wa = await _agent(client, sp, "brk-idor-a")
    wb = await _agent(client, sp, "brk-idor-b")
    ka, _ = await _wallet_key(client, wa, "ka")
    await record_audit_event(
        event="mcp.invoke", wallet_id=wa, ok=True, request_id="idor-own"
    )
    await record_audit_event(
        event="billing.charge", wallet_id=wb, ok=True, request_id="idor-victim-1"
    )
    await record_audit_event(
        event="billing.charge",
        wallet_id=wb,
        ok=False,
        error="x",
        request_id="idor-victim-2",
    )
    headers = {"X-API-Key": ka}

    # Cross-wallet event list is refused outright.
    r = await client.get(f"/v1/audit/events?wallet_id={wb}", headers=headers)
    assert r.status_code == 403, r.text

    # An unscoped list means "my events", even with other wallets present.
    r = await client.get("/v1/audit/events", headers=headers)
    assert r.status_code == 200, r.text
    assert {e["wallet_id"] for e in r.json()["events"]} == {wa}

    # A foreign key_id filter cannot widen the scope to another wallet.
    r = await client.get(
        f"/v1/audit/events?wallet_id={wa}&key_id=k-victim", headers=headers
    )
    assert r.status_code == 200, r.text
    assert all(e["wallet_id"] == wa for e in r.json()["events"])

    # The summary is computed over the caller's own rows only.
    r = await client.get("/v1/audit/summary", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1, body
    assert body["by_wallet"] == {wa: 1}, body

    # Chain verification for another wallet is refused; for no wallet it
    # verifies the caller's own chain.
    r = await client.post(
        "/v1/audit/verify-chain", json={"wallet_id": wb}, headers=headers
    )
    assert r.status_code == 403, r.text
    r = await client.post("/v1/audit/verify-chain", json={}, headers=headers)
    assert r.status_code == 200, r.text


@pytest.mark.anyio
async def test_caller_chosen_jwt_scopes_grant_no_admin_power(
    client, clean_database, monkeypatch
):
    from app.core.config import get_settings
    from app.core.jwt import get_jwt_service

    monkeypatch.setenv(
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU=",
    )
    get_settings.cache_clear()
    try:
        sp = await _sponsor(client, "brk-jwt")
        w = await _agent(client, sp, "brk-jwt-a")
        _, key_id = await _wallet_key(client, w)
        # Scopes are caller-chosen at mint time; claiming admin-shaped ones
        # must not open admin routes or other wallets.
        token = get_jwt_service().create_access_token(
            wallet_id=w,
            key_id=key_id,
            scopes=[
                "admin",
                "bootstrap",
                "bootstrap_admin",
                "*:*",
                "billing:charge",
                "tool:invoke",
            ],
        )
        headers = {"Authorization": f"Bearer {token}"}
        for method, path, body in [
            ("GET", "/v1/policies", None),
            ("POST", "/v1/policies", {"wallet_id": w, "name": "n"}),
            (
                "POST",
                "/v1/billing/wallets/sponsor",
                {"sponsor_name": "s", "email": "s@e.com"},
            ),
            ("POST", "/v1/receipts/reconciliation/refunds/nope/retry", None),
        ]:
            if method == "GET":
                r = await client.get(path, headers=headers)
            else:
                r = await client.post(path, json=body, headers=headers)
            assert r.status_code == 403, (method, path, r.status_code, r.text)
        r = await client.get("/v1/audit/events?wallet_id=some-other", headers=headers)
        assert r.status_code == 403, r.text
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_policy_update_ignores_ownership_and_privilege_fields(
    client, clean_database
):
    sp = await _sponsor(client, "brk-mass")
    w = await _agent(client, sp, "brk-mass-a")
    w2 = await _agent(client, sp, "brk-mass-b")
    r = await client.post(
        "/v1/policies", json={"wallet_id": w, "name": "o"}, headers=ADMIN
    )
    assert r.status_code == 201, r.text
    policy_id = r.json()["policy_id"]
    r = await client.patch(
        f"/v1/policies/{policy_id}",
        json={
            "name": "renamed",
            "wallet_id": w2,
            "policy_id": "hijacked",
            "is_admin": True,
            "scopes": ["admin"],
        },
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wallet_id"] == w, body
    assert body["policy_id"] == policy_id, body
    assert body["name"] == "renamed", body


@pytest.mark.anyio
async def test_policy_create_unknown_wallet_is_404_not_500(client, clean_database):
    r = await client.post(
        "/v1/policies",
        json={"wallet_id": "no-such-wallet", "name": "x"},
        headers=ADMIN,
    )
    assert r.status_code == 404, (r.status_code, r.text[:300])
    assert r.json()["detail"]["error"] == "wallet_not_found", r.text[:300]


@pytest.mark.anyio
async def test_rotation_logs_limit_is_validated(client, clean_database):
    sp = await _sponsor(client, "brk-lim")
    w = await _agent(client, sp, "brk-lim-a")
    _, key_id = await _wallet_key(client, w)
    for i in range(3):
        r = await client.post(
            "/v1/api-keys/rotate",
            json={
                "wallet_id": w,
                "key_id": key_id,
                "revoke_old": False,
                "reason": f"seed-{i}",
            },
            headers=ADMIN,
        )
        assert r.status_code == 200, r.text
        key_id = r.json()["new_key"]["key_id"]

    r = await client.get(f"/v1/api-keys/{w}/logs?limit=1", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    # SQLite reads LIMIT -1 as "no limit", so an unvalidated negative limit
    # silently disabled pagination on this backend.
    for bad in ("-1", "0"):
        r = await client.get(f"/v1/api-keys/{w}/logs?limit={bad}", headers=ADMIN)
        assert r.status_code == 422, (bad, r.status_code, r.text[:200])
    r = await client.get(
        f"/v1/api-keys/{w}/logs?limit={_LOGS_LIMIT_MAX + 1}", headers=ADMIN
    )
    assert r.status_code == 422, (r.status_code, r.text[:200])


@pytest.mark.anyio
async def test_key_management_reads_stay_in_wallet(client, clean_database):
    sp = await _sponsor(client, "brk-keyidor")
    wa = await _agent(client, sp, "brk-keyidor-a")
    wb = await _agent(client, sp, "brk-keyidor-b")
    ka, _ = await _wallet_key(client, wa, "ka")
    headers = {"X-API-Key": ka}
    r = await client.get(f"/v1/api-keys/{wb}", headers=headers)
    assert r.status_code == 403, r.text
    r = await client.get(f"/v1/api-keys/{wb}/logs", headers=headers)
    assert r.status_code == 403, r.text
    r = await client.post(
        "/v1/api-keys/rotate", json={"wallet_id": wb}, headers=headers
    )
    assert r.status_code == 403, r.text
    r = await client.post(
        "/v1/api-keys/emergency-revoke", json={"wallet_id": wb}, headers=headers
    )
    assert r.status_code == 403, r.text
    r = await client.post(
        "/v1/api-keys", json={"wallet_id": wb, "key_name": "x"}, headers=headers
    )
    assert r.status_code == 403, r.text


@pytest.mark.anyio
async def test_malformed_audit_and_admin_input_never_500s(client, clean_database):
    sp = await _sponsor(client, "brk-mal")
    w = await _agent(client, sp, "brk-mal-a")
    key, _ = await _wallet_key(client, w)
    headers = {"X-API-Key": key}
    cases = [
        ("GET", f"/v1/audit/events?wallet_id={w}&limit=abc", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={w}&limit=0", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={w}&limit=-5", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={w}&limit=999999999", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={w}&offset=-3", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={w}&summary=maybe", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={w}&created_after=nope", None, headers),
        ("GET", f"/v1/audit/events?wallet_id={'x' * 10000}", None, ADMIN),
        (
            "POST",
            "/v1/audit/verify-chain",
            {"wallet_id": w, "created_after": "zzz"},
            headers,
        ),
        ("POST", "/v1/receipts/verify", {"receipt_id": 12345}, headers),
        ("PATCH", "/v1/policies/x", {"name": 123}, ADMIN),
    ]
    for method, path, body, hdrs in cases:
        if method == "GET":
            r = await client.get(path, headers=hdrs)
        elif method == "PATCH":
            r = await client.patch(path, json=body, headers=hdrs)
        else:
            r = await client.post(path, json=body, headers=hdrs)
        assert r.status_code in (200, 400, 401, 403, 404, 422), (
            method,
            path,
            r.status_code,
            r.text[:200],
        )
        assert r.status_code != 500, (method, path, r.text[:200])


@pytest.mark.anyio
async def test_presented_bearer_is_authoritative_over_api_key(client, clean_database):
    sp = await _sponsor(client, "brk-hdr")
    w = await _agent(client, sp, "brk-hdr-a")
    key, _ = await _wallet_key(client, w)
    # An invalid Bearer [REDACTED] must not fall back to the accompanying valid key.
    r = await client.get(
        f"/v1/audit/events?wallet_id={w}",
        headers={"X-API-Key": key, "Authorization": "Bearer garbage-token"},
    )
    assert r.status_code == 401, (r.status_code, r.text[:200])
    # Unknown keys are refused as forbidden; short or empty keys as bad
    # credentials. None of them reach the handler.
    r = await client.get(
        f"/v1/audit/events?wallet_id={w}",
        headers={"X-API-Key": "amw_unknown_key_12345"},
    )
    assert r.status_code == 403, (r.status_code, r.text[:200])
    for bad in ("", "short"):
        r = await client.get(
            f"/v1/audit/events?wallet_id={w}", headers={"X-API-Key": bad}
        )
        assert r.status_code in (401, 403), (bad, r.status_code)


@pytest.mark.anyio
async def test_idempotency_key_does_not_cross_wallets(client, clean_database):
    sp = await _sponsor(client, "brk-idem")
    wa = await _agent(client, sp, "brk-idem-a")
    wb = await _agent(client, sp, "brk-idem-b")
    headers = {"X-API-Key": "test-key", "Idempotency-Key": "shared-key-9"}
    r1 = await client.post(
        "/v1/api-keys", json={"wallet_id": wa, "key_name": "first"}, headers=headers
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        "/v1/api-keys", json={"wallet_id": wb, "key_name": "second"}, headers=headers
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["wallet_id"] == wb, r2.text
    assert r2.json()["key_id"] != r1.json()["key_id"], r2.text


@pytest.mark.anyio
async def test_concurrent_rotate_of_one_key_fails_closed(client, clean_database):
    sp = await _sponsor(client, "brk-crot")
    w = await _agent(client, sp, "brk-crot-a")
    key, key_id = await _wallet_key(client, w, "victim")
    headers = {"X-API-Key": key}

    async def rotate(i: int):
        return await client.post(
            "/v1/api-keys/rotate",
            json={
                "wallet_id": w,
                "key_id": key_id,
                "revoke_old": True,
                "reason": f"race-{i}",
            },
            headers={**headers, "Idempotency-Key": f"brk-race-{i}"},
        )

    first, second = await asyncio.gather(rotate(0), rotate(1))
    codes = sorted([first.status_code, second.status_code])
    # Exactly one rotation wins; the loser is refused because the key is no
    # longer active, so no second live key is minted on the losing path.
    assert codes[0] == 200, (codes, first.text[:200], second.text[:200])
    assert codes[1] in (404, 409, 422), (codes, first.text[:200], second.text[:200])
