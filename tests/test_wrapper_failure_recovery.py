"""Failure recovery for the real autogen/crewai/langchain wrapper bodies.

The happy path (permit, invoke, receipt, replay) is pinned by each wrapper's
own suite and by tests/test_wrapper_permit_retry_contract.py. These tests pin
the failure paths that move money or decide whether money moves:

* a denied permit surfaces instead of being cached as authority, and the
  retry after recovery replays the identical permit body;
* a lost invoke response reuses the recorded permit instead of minting another;
* the permit and the invoke are bound to the same wallet;
* blank or non-string idempotency keys are refused before any transport;
* the non-governed helpers (discover, balance) send the documented requests.

Optional frameworks are stubbed the way
tests/test_wrapper_permit_retry_contract.py does, so these run in the root
suite with no framework installed. Like that file, they exercise the real
wrapper bodies, not the stubs.
"""

import ast
import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from b2a_sdk.client import AgentMiddlewareClient
from b2a_sdk.errors import PermitDeniedError, TransportError

ROOT = Path(__file__).resolve().parents[1]
WALLET = "wallet-local"
TOOL = "partner.search"
CALL = dict(
    tool_name=TOOL,
    idempotency_key="logical-action",
    permit_idempotency_key="permit-key",
    arguments={},
)


def _load_wrapper(monkeypatch: pytest.MonkeyPatch, framework: str) -> ModuleType:
    """Load the real wrapper body with the framework import stubbed."""
    if framework == "autogen":
        names = (
            "autogen",
            "autogen.agentchat",
            "autogen.agentchat.conversable_agent",
        )
        for name in names:
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
        sys.modules[names[-1]].ConversableAgent = type("ConversableAgent", (), {})
    elif framework == "crewai":

        class BaseTool(BaseModel):
            model_config = ConfigDict(arbitrary_types_allowed=True)
            args_schema: Any = None

        for name in ("crewai", "crewai.tools"):
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
        sys.modules["crewai.tools"].BaseTool = BaseTool
    else:

        class StructuredTool:
            @staticmethod
            def from_function(**kwargs: Any) -> SimpleNamespace:
                return SimpleNamespace(**kwargs)

        for name in ("langchain_core", "langchain_core.tools"):
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
        sys.modules["langchain_core.tools"].StructuredTool = StructuredTool

    package_name = f"_failure_recovery_{framework}"
    source = ROOT / f"wrappers/{framework}-agent-middleware/src/{framework}_b2a"
    package = ModuleType(package_name)
    package.__path__ = [str(source)]
    monkeypatch.setitem(sys.modules, package_name, package)
    filename = "_tools.py" if framework == "langchain" else "tool.py"
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.tool", source / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _permit_payload() -> dict:
    return {
        "permit_id": "permit-original",
        "issuer_wallet_id": WALLET,
        "subject_wallet_id": WALLET,
        "subject_key_id": "key-local",
        "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
        "allowed_tools": [TOOL],
        "max_credits": "100",
        "spent_credits": "0",
        "expires_at": datetime.now(timezone.utc).isoformat(),
        "nonce": "nonce-local",
        "status": "active",
        "signature": "synthetic",
        "key_id": "key-local",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
    }


def _receipt_payload() -> dict:
    return {
        "receipt_id": "receipt-original",
        "permit_id": "permit-original",
        "wallet_id": WALLET,
        "key_id": "key-local",
        "tool": TOOL,
        "request_hash": "request-hash",
        "response_hash": "response-hash",
        "ledger_entry_id": "ledger-local",
        "dispatch_attempt_id": "dispatch-local",
        "credits_authorized": "1",
        "credits_charged": "1",
        "outcome": "success",
        "audit_event_id": "audit-local",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signature": "synthetic",
        "signature_key_id": "key-local",
        "idempotency_key": CALL["idempotency_key"],
    }


def _invoke_envelope(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "content": [{"type": "text", "text": "ok"}],
                "structuredContent": {},
                "isError": False,
                "receipt": _receipt_payload(),
            },
        },
    )


class _FlakyGateway:
    """Permits deniable on demand; the first invoke response losable on demand."""

    def __init__(self) -> None:
        self.deny_permits = False
        self.lose_first_invoke = False
        self.permit_bodies: list[bytes] = []
        self.permit_json: list[dict] = []
        self.invoke_bodies: list[dict] = []
        self.invoke_count = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/permits":
            self.permit_bodies.append(request.content)
            self.permit_json.append(json.loads(request.content))
            if self.deny_permits:
                return httpx.Response(403, json={"detail": "permit_tool_not_allowed"})
            return httpx.Response(201, json=_permit_payload())
        assert request.url.path == "/mcp/messages"
        self.invoke_count += 1
        self.invoke_bodies.append(json.loads(request.content))
        if self.lose_first_invoke and self.invoke_count == 1:
            raise httpx.ConnectError("synthetic lost invoke response", request=request)
        return _invoke_envelope(request)


@asynccontextmanager
async def _session(monkeypatch, framework, gateway):
    """Yield (call, raw) bound to ONE tool instance and client.

    One instance matters: the permit body cache lives on the tool, so a retry
    that must replay the identical body has to go through the same object,
    exactly like a real agent retrying after a failure. ``call`` returns the
    receipt id (raising on failure, with crewai's "Error: ..." strings
    converted to ValueError); ``raw`` returns the wrapper's raw value so
    tests can inspect crewai's error strings.
    """
    module = _load_wrapper(monkeypatch, framework)
    async with AgentMiddlewareClient(
        "synthetic",
        base_url="http://local.invalid",
        transport=httpx.MockTransport(gateway),
    ) as client:
        if framework == "autogen":
            tool = module.B2AFunctionTool(api_key="synthetic", wallet_id=WALLET)
            await tool.client.close()
            tool.client = client

            async def call(**kwargs):
                result = await tool.call_mcp_tool(**(kwargs or CALL))
                return result["receipt_id"]

            yield call, call
        elif framework == "crewai":
            tool = module.CrewAIB2ATool(api_key="synthetic", wallet_id=WALLET)
            tool.client = client

            async def call(**kwargs):
                value = await tool._arun("call_tool", **(kwargs or CALL))
                if value.startswith("Error:"):
                    raise ValueError(value)
                return ast.literal_eval(value)["receipt_id"]

            async def raw(**kwargs):
                return await tool._arun("call_tool", **(kwargs or CALL))

            yield call, raw
        else:
            tool = module.create_mcp_tool(client, wallet_id=WALLET)

            async def call(**kwargs):
                value = await tool.coroutine(**(kwargs or CALL))
                return ast.literal_eval(value)["receipt_id"]

            yield call, call


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["autogen", "crewai", "langchain"])
async def test_permit_denial_is_surfaced_and_retry_replays_identical_body(
    monkeypatch, framework
):
    gateway = _FlakyGateway()
    gateway.deny_permits = True
    async with _session(monkeypatch, framework, gateway) as (call, raw):
        if framework == "crewai":
            denied = await raw()
            assert denied.startswith("Error:") and "permit_" in denied
        else:
            with pytest.raises(PermitDeniedError, match="permit_"):
                await call()

        gateway.deny_permits = False
        assert await call() == "receipt-original"

    assert len(gateway.permit_bodies) == 2
    assert gateway.permit_bodies[0] == gateway.permit_bodies[1]
    assert gateway.invoke_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["autogen", "crewai", "langchain"])
async def test_lost_invoke_response_reuses_permit_on_retry(monkeypatch, framework):
    gateway = _FlakyGateway()
    gateway.lose_first_invoke = True
    async with _session(monkeypatch, framework, gateway) as (call, raw):
        if framework == "crewai":
            failed = await raw()
            assert failed.startswith("Error:")
        else:
            with pytest.raises(TransportError):
                await call()

        assert await call() == "receipt-original"
    # The permit was already issued and cached, so the retry sends no new
    # permit request at all; only the invoke is re-attempted under its key.
    assert len(gateway.permit_bodies) == 1
    assert gateway.invoke_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["autogen", "crewai", "langchain"])
async def test_permit_and_invoke_are_bound_to_the_same_wallet(monkeypatch, framework):
    gateway = _FlakyGateway()
    async with _session(monkeypatch, framework, gateway) as (call, _raw):
        assert await call() == "receipt-original"

    permit = gateway.permit_json[0]
    assert permit["issuer_wallet_id"] == WALLET
    assert permit["subject_wallet_id"] == WALLET
    assert permit["allowed_tools"] == [TOOL]

    context = gateway.invoke_bodies[0]["params"]["mcpContext"]
    assert context["wallet_id"] == WALLET
    assert context["permit_id"] == "permit-original"
    assert context["idempotency_key"] == CALL["idempotency_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["autogen", "crewai", "langchain"])
async def test_blank_permit_key_is_refused_before_transport(monkeypatch, framework):
    sent: list[httpx.Request] = []
    gateway = _FlakyGateway()

    async def recording(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return await gateway(request)

    async with _session(monkeypatch, framework, recording) as (call, raw):
        blank = {**CALL, "permit_idempotency_key": "  "}
        if framework == "crewai":
            refused = await raw(**blank)
            assert "permit_idempotency_key is required" in refused
        else:
            with pytest.raises(ValueError, match="permit_idempotency_key"):
                await call(**blank)
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["autogen", "crewai", "langchain"])
@pytest.mark.parametrize("field", ["idempotency_key", "permit_idempotency_key"])
async def test_non_string_keys_are_rejected_before_transport(
    monkeypatch, framework, field
):
    sent: list[httpx.Request] = []

    async def recording(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(404)

    call = {**CALL, field: 12345}
    async with _session(monkeypatch, framework, recording) as (invoke, raw):
        if framework == "crewai":
            refused = await raw(**call)
            assert "must not be blank" in refused
        else:
            with pytest.raises(ValueError, match="must not be blank"):
                await invoke(**call)
    assert sent == []


@pytest.mark.asyncio
async def test_autogen_discover_and_balance_send_documented_requests(monkeypatch):
    sent: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path == "/mcp/tools.json":
            return httpx.Response(
                200,
                json={
                    "tools": [
                        {
                            "name": TOOL,
                            "description": "Search partners",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                },
            )
        if request.url.path == f"/v1/billing/wallets/{WALLET}":
            return httpx.Response(200, json={"balance": 42.5})
        return httpx.Response(404)

    module = _load_wrapper(monkeypatch, "autogen")
    async with AgentMiddlewareClient(
        "synthetic",
        base_url="http://local.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        tool = module.B2AFunctionTool(api_key="synthetic", wallet_id=WALLET)
        await tool.client.close()
        tool.client = client
        discovered = await tool.discover_tools()
        balance = await tool.get_wallet_balance()

    assert discovered == [
        {
            "name": TOOL,
            "description": "Search partners",
            "input_schema": {"type": "object"},
        }
    ]
    assert balance == 42.5
    assert [(r.method, r.url.path) for r in sent] == [
        ("GET", "/mcp/tools.json"),
        ("GET", f"/v1/billing/wallets/{WALLET}"),
    ]
    assert all(r.headers["X-API-Key"] == "synthetic" for r in sent)


@pytest.mark.asyncio
async def test_crewai_discover_balance_and_unknown_operation(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mcp/tools.json":
            return httpx.Response(
                200, json={"tools": [{"name": TOOL, "description": "Search partners"}]}
            )
        if request.url.path == f"/v1/billing/wallets/{WALLET}":
            return httpx.Response(200, json={"balance": 7.5})
        return httpx.Response(404)

    module = _load_wrapper(monkeypatch, "crewai")
    async with AgentMiddlewareClient(
        "synthetic",
        base_url="http://local.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        tool = module.CrewAIB2ATool(api_key="synthetic", wallet_id=WALLET)
        tool.client = client
        discovered = await tool._arun(operation="discover_tools")
        balance = await tool._arun(operation="balance")
        unknown = await tool._arun(operation="teleport")

    assert TOOL in discovered
    assert balance == "Balance: 7.5 credits"
    assert unknown == "Unknown operation: teleport"


@pytest.mark.asyncio
async def test_langchain_wallet_tool_and_langgraph_factories(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/billing/wallets/{WALLET}":
            return httpx.Response(200, json={"balance": 11.25})
        return httpx.Response(404)

    module = _load_wrapper(monkeypatch, "langchain")
    async with AgentMiddlewareClient(
        "synthetic",
        base_url="http://local.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        wallet_tool = module.create_wallet_tool(client, wallet_id=WALLET)
        assert await wallet_tool.coroutine() == "Balance: 11.25 credits"

        bundled = module.create_langgraph_tools(client, wallet_id=WALLET)
        assert [t.name for t in bundled] == ["mcp_tool_call", "wallet_balance"]


@pytest.mark.xfail(
    strict=True, reason="BUG: CrewAIB2ATool never attaches MCPToolSchema as args_schema"
)
async def test_crewai_tool_exposes_its_input_schema(monkeypatch):
    """MCPToolSchema/WalletBalanceSchema are defined but never wired up.

    Without args_schema a real CrewAI agent run derives the tool schema from
    the _run signature (operation only), so the model can never supply
    tool_name, idempotency keys or arguments through the framework path.
    """
    module = _load_wrapper(monkeypatch, "crewai")
    tool = module.CrewAIB2ATool(api_key="synthetic", wallet_id=WALLET)
    assert tool.args_schema is module.MCPToolSchema
