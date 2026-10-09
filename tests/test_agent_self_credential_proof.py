"""Exit-code coverage for scripts/agent_self_credential_proof.py.

The proof drives a self-provisioned key through seven invariants over HTTP.
These tests run it against an in-process fake of the trust plane
(``httpx.MockTransport``) that signs real Ed25519 receipts, then vary only the
scope-denial step: the run may report "ALL INVARIANTS HELD" and exit 0 only
when every invariant actually ran and held.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import sys

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts import agent_self_credential_proof as proof
from app.services.signing_keys import RECEIPT_CANONICALIZATION

WALLET = "agt-proof"
KEY_ID = "key_proof"
KID = "test-ed25519"
# Mirror of the real trust-keys envelope (app/routers/well_known.py
# get_trust_keys_json): the proof only reads ``keys``, but the conformance
# test below pins the envelope fields so a thin fake cannot silently diverge.
TRUST_KEYS_PORTABLE_PATH = "/v1/receipts/{receipt_id}/portable"


class FakeTrustPlane:
    """Answers the proof's requests the way a healthy local instance does."""

    def __init__(self, scope_denial: str) -> None:
        self.scope_denial = scope_denial
        self.signing_key = Ed25519PrivateKey.generate()
        self.debits: list[dict] = []
        self.signed: dict[str, str] = {}
        self.by_key: dict[str, tuple[str, str]] = {}
        self.in_flight: set[str] = set()
        self._ids = itertools.count(1)

    def _sign(self, tool: str, outcome: str, charged: str) -> dict:
        receipt_id = f"rcpt-{next(self._ids)}"
        fields = {
            "receipt_id": receipt_id,
            "wallet_id": WALLET,
            "tool": tool,
            "outcome": outcome,
            "credits_charged": charged,
        }
        self.signed[receipt_id] = json.dumps(
            fields, sort_keys=True, separators=(",", ":")
        )
        return {"receipt_id": receipt_id, "credits_charged": charged}

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/dev-keys/self-provision":
            return httpx.Response(
                201,
                json={"wallet_id": WALLET, "key_id": KEY_ID, "api_key": "b2a_x"},
            )
        if path == "/v1/permits":
            return httpx.Response(201, json={"permit_id": "permit-proof"})
        if path == f"/v1/billing/ledger/{WALLET}":
            return httpx.Response(200, json={"entries": list(self.debits)})
        if path == "/.well-known/trust-keys.json":
            public = self.signing_key.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw
            )
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "issuer": "",
                    "alg": "Ed25519",
                    "canonicalization": RECEIPT_CANONICALIZATION,
                    "keys": [
                        {
                            "kid": KID,
                            "alg": "Ed25519",
                            "status": "active",
                            "public_key_b64": base64.b64encode(public).decode(),
                        }
                    ],
                    "verification": {
                        "portable_receipt": TRUST_KEYS_PORTABLE_PATH,
                    },
                },
            )
        if path.startswith("/v1/receipts/") and path.endswith("/portable"):
            receipt_id = path.split("/")[3]
            signing_input = self.signed[receipt_id]
            signature = self.signing_key.sign(signing_input.encode())
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "receipt_id": receipt_id,
                    "issuer": "",
                    "alg": "Ed25519",
                    "kid": KID,
                    "canonicalization": RECEIPT_CANONICALIZATION,
                    "signing_input": signing_input,
                    "signature": base64.b64encode(signature).decode(),
                    "keys_url": "/.well-known/trust-keys.json",
                },
            )
        if path == f"/mcp/tools/{proof.ALLOWED_TOOL}/invoke":
            return await self._invoke(json.loads(request.content))
        if path == f"/mcp/tools/{proof.BLOCKED_TOOL}/invoke":
            return self._blocked_tool()
        return httpx.Response(404, json={"detail": "not found"})

    async def _invoke(self, body: dict) -> httpx.Response:
        context = body["mcp_context"]
        if not context.get("permit_id"):
            return httpx.Response(403, json={"detail": {"error": "permit_required"}})
        key = context["idempotency_key"]
        text = body["arguments"]["text"]
        if key in self.in_flight:
            return httpx.Response(
                409, json={"detail": {"error": "idempotency_in_progress"}}
            )
        if key in self.by_key:
            cached_text, receipt_id = self.by_key[key]
            if cached_text != text:
                return httpx.Response(
                    400, json={"detail": {"error": "idempotency_key_reused"}}
                )
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "isError": False,
                    "receipt": {"receipt_id": receipt_id},
                },
            )
        self.in_flight.add(key)
        await asyncio.sleep(0.01)  # concurrent same-key callers see it in flight
        self.debits.append({"action": "debit", "amount": "-2"})
        receipt = self._sign(proof.ALLOWED_TOOL, "success", "2")
        self.by_key[key] = (text, receipt["receipt_id"])
        self.in_flight.discard(key)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
                "receipt": receipt,
            },
        )

    def _blocked_tool(self) -> httpx.Response:
        if self.scope_denial == "tool-not-registered":
            return httpx.Response(
                404, json={"detail": f"Tool not found: {proof.BLOCKED_TOOL}"}
            )
        if self.scope_denial == "unstructured-detail":
            return httpx.Response(403, json={"detail": "permit_tool_not_allowed"})
        detail: dict = {"error": "permit_tool_not_allowed"}
        if self.scope_denial == "signed-denial":
            detail["receipt"] = self._sign(proof.BLOCKED_TOOL, "denied", "0")
        return httpx.Response(403, json={"detail": detail})


def _run_proof(
    monkeypatch: pytest.MonkeyPatch, scope_denial: str
) -> tuple[int, FakeTrustPlane]:
    fake = FakeTrustPlane(scope_denial)
    real_async_client = httpx.AsyncClient

    def mock_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return real_async_client(
            *args, transport=httpx.MockTransport(fake.handle), **kwargs
        )

    monkeypatch.setattr(proof.httpx, "AsyncClient", mock_client)
    monkeypatch.setattr(proof, "failures", [])
    monkeypatch.setattr(proof, "skipped", [], raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent_self_credential_proof.py", "--base-url", "http://127.0.0.1:8000"],
    )
    return proof.main(), fake


def test_signed_scope_denial_lets_every_invariant_hold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, fake = _run_proof(monkeypatch, "signed-denial")

    out = capsys.readouterr().out
    assert code == 0, out
    assert "ALL INVARIANTS HELD" in out
    assert "[FAIL]" not in out
    # Three receipts verified: first invoke, the burst winner, and the denial.
    assert out.count("signature valid") == len(fake.signed) == 3


def test_unregistered_scope_denial_tool_is_not_reported_as_held(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _fake = _run_proof(monkeypatch, "tool-not-registered")

    out = capsys.readouterr().out
    assert code == 3, out
    assert "ALL INVARIANTS HELD" not in out
    assert "SKIPPED: scope-denial" in out


@pytest.mark.parametrize(
    ("scope_denial", "failed_check"),
    [
        ("unsigned-denial", "signed denial receipt issued"),
        ("unstructured-detail", "denial detail is structured"),
    ],
)
def test_scope_denial_without_signed_structured_evidence_fails(
    scope_denial: str,
    failed_check: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _fake = _run_proof(monkeypatch, scope_denial)

    out = capsys.readouterr().out
    assert code == 1, out
    assert "ALL INVARIANTS HELD" not in out
    assert f"[FAIL] {failed_check}" in out


def _fake_response(
    fake: FakeTrustPlane, method: str, path: str, body: dict | None = None
) -> httpx.Response:
    request = httpx.Request(method, f"http://127.0.0.1:8000{path}", json=body)
    return asyncio.run(fake.handle(request))


def test_fake_matches_real_server_contract() -> None:
    """Conformance pin: the fake must satisfy the real response contracts.

    The proof only reads a subset of each body, so a thin fake stays green
    while the real server drifts. Every response below is validated against
    the real Pydantic model or the real status mapping, so a drift on either
    side breaks this test instead of passing silently.
    """
    from app.routers.mcp import ToolCallResponse
    from app.schemas.trust import PortableReceiptResponse

    fake = FakeTrustPlane("signed-denial")

    provisioned = _fake_response(
        fake, "POST", "/v1/dev-keys/self-provision", {"agent_id": "probe"}
    )
    assert provisioned.status_code == 201
    assert {"wallet_id", "key_id", "api_key"} <= set(provisioned.json())

    permit = _fake_response(fake, "POST", "/v1/permits", {})
    assert permit.status_code == 201
    assert permit.json()["permit_id"]

    ledger = _fake_response(fake, "GET", f"/v1/billing/ledger/{WALLET}")
    assert ledger.status_code == 200
    assert isinstance(ledger.json()["entries"], list)

    keys = _fake_response(fake, "GET", "/.well-known/trust-keys.json")
    assert keys.status_code == 200
    envelope = keys.json()
    assert envelope["canonicalization"] == RECEIPT_CANONICALIZATION
    assert envelope["verification"]["portable_receipt"] == TRUST_KEYS_PORTABLE_PATH
    (entry,) = envelope["keys"]
    assert entry["kid"] == KID
    assert len(base64.b64decode(entry["public_key_b64"])) == 32

    invoke_body = {
        "name": proof.ALLOWED_TOOL,
        "arguments": {"text": "conformance"},
        "mcp_context": {
            "wallet_id": WALLET,
            "permit_id": "permit-proof",
            "idempotency_key": "conformance-1",
        },
    }
    first = _fake_response(
        fake, "POST", f"/mcp/tools/{proof.ALLOWED_TOOL}/invoke", invoke_body
    )
    assert first.status_code == 200
    success = ToolCallResponse.model_validate(first.json())
    assert success.receipt is not None
    assert success.receipt["receipt_id"]
    assert success.isError is False

    replay = _fake_response(
        fake, "POST", f"/mcp/tools/{proof.ALLOWED_TOOL}/invoke", invoke_body
    )
    assert replay.status_code == 200
    cached = ToolCallResponse.model_validate(replay.json())
    assert cached.receipt is not None
    assert cached.receipt["receipt_id"] == success.receipt["receipt_id"]

    conflict = _fake_response(
        fake,
        "POST",
        f"/mcp/tools/{proof.ALLOWED_TOOL}/invoke",
        {
            "name": proof.ALLOWED_TOOL,
            "arguments": {"text": "different payload"},
            "mcp_context": {
                "wallet_id": WALLET,
                "permit_id": "permit-proof",
                "idempotency_key": "conformance-1",
            },
        },
    )
    assert conflict.status_code == 400
    assert conflict.json()["detail"]["error"] == "idempotency_key_reused"

    fake.in_flight.add("conformance-busy")
    busy = asyncio.run(
        fake._invoke(
            {
                "arguments": {"text": "x"},
                "mcp_context": {
                    "wallet_id": WALLET,
                    "permit_id": "permit-proof",
                    "idempotency_key": "conformance-busy",
                },
            }
        )
    )
    assert busy.status_code == 409
    assert busy.json()["detail"]["error"] == "idempotency_in_progress"

    no_permit = asyncio.run(
        fake._invoke(
            {
                "arguments": {"text": "ungoverned"},
                "mcp_context": {"wallet_id": WALLET},
            }
        )
    )
    assert no_permit.status_code == 403

    denial = fake._blocked_tool()
    assert denial.status_code == 403
    detail = denial.json()["detail"]
    assert detail["error"] == "permit_tool_not_allowed"
    assert detail["receipt"]["receipt_id"]

    receipt_id = detail["receipt"]["receipt_id"]
    portable = _fake_response(fake, "GET", f"/v1/receipts/{receipt_id}/portable")
    assert portable.status_code == 200
    bundle = PortableReceiptResponse.model_validate(portable.json())
    assert bundle.receipt_id == receipt_id
    assert bundle.kid == KID
    assert bundle.canonicalization == RECEIPT_CANONICALIZATION
    assert bundle.keys_url == "/.well-known/trust-keys.json"


@pytest.mark.asyncio
async def test_fake_denial_matches_live_server_denial(clean_database) -> None:
    """The fake's scope-denial answer must match the real server's answer.

    A live out-of-scope invoke against the real app pins the status code and
    the denial reason string; the fake must answer the same way, or the
    proof's scope-denial invariant is checking fiction.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.schemas.billing import ServiceCategory
    from app.services.service_registry import get_service_registry
    from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

    registry = get_service_registry()

    def echo(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id="proof-conformance-allowed",
        name="Proof Conformance Allowed",
        description="Conformance pin for the self-credential proof fake",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
    registry.register_local(
        service_id="proof-conformance-blocked",
        name="Proof Conformance Blocked",
        description="Conformance pin for the self-credential proof fake",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            agent = await provision_agent_wallet(client)
            permit = await create_tool_permit(
                client,
                wallet_id=agent["agent_wallet_id"],
                key_id=agent["key_id"],
                tool_name="proof-conformance-allowed",
                idem_key="proof-conformance-permit",
            )
            live = await client.post(
                "/mcp/tools/proof-conformance-blocked/invoke",
                json={
                    "name": "proof-conformance-blocked",
                    "arguments": {"message": "hi"},
                    "mcp_context": {
                        "wallet_id": agent["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "proof-conformance-deny",
                    },
                },
                headers=agent["agent_headers"],
            )
    finally:
        registry.unregister_local("proof-conformance-allowed")
        registry.unregister_local("proof-conformance-blocked")

    assert live.status_code == 403, live.text
    live_detail = live.json()["detail"]
    assert live_detail["error"] == "permit_tool_not_allowed"

    fake_denial = FakeTrustPlane("signed-denial")._blocked_tool()
    assert fake_denial.status_code == live.status_code
    assert fake_denial.json()["detail"]["error"] == live_detail["error"]
