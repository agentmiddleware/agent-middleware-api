"""AutoGen function tools for Agent Middleware API."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from autogen.agentchat.conversable_agent import ConversableAgent

from b2a_sdk.models import PermitRequest

from .client import B2AClient

#: The trust plane stores a client key verbatim in a 128-character column and
#: ``b2a_sdk`` enforces the same bound before sending. Checked here so a bad
#: key fails before any record is written or any HTTP call goes out. Mirrors
#: ``openai_b2a.runner.MAX_IDEMPOTENCY_KEY_LENGTH``.
MAX_IDEMPOTENCY_KEY_LENGTH = 128


def _validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-blank string")
    if not value.isascii() or not value.isprintable() or value.strip() != value:
        raise ValueError(
            f"{label} must be printable ASCII with no surrounding whitespace"
        )
    if len(value) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(
            f"{label} is too long (limit {MAX_IDEMPOTENCY_KEY_LENGTH} characters)"
        )
    return value


class B2AFunctionTool:
    """AutoGen-compatible function tool for Agent Middleware API via governed permit→invoke→receipt flow.

    Provides MCP tools and wallet operations as callable functions for AutoGen agents.
    All invocations return signed receipts.
    """

    def __init__(
        self,
        api_key: str,
        wallet_id: str,
        base_url: str = "https://api.thisisatest.tech",
        permit_budget: Decimal = Decimal("100"),
        permit_ttl_minutes: int = 30,
        allowed_tools: list[str] | None = None,
        key_store_path: str | Path | None = None,
    ):
        """Configure the tool.

        Args:
            allowed_tools: when given, ``call_mcp_tool`` refuses any tool
                name not on the list. Use :meth:`register_tool` to add names
                instead of passing raw strings from the model.
            key_store_path: when given, the permit-id cache and the permit
                request snapshots persist to this JSON file (rewritten
                atomically on every update). A resumed process constructed
                with the same path reuses the recorded permit ids and
                resends byte-identical permit bodies instead of minting
                fresh timestamps under the same keys.
        """
        self.client = B2AClient(
            api_key=api_key,
            base_url=base_url,
        )
        self.wallet_id = wallet_id
        self.permit_budget = permit_budget
        self.permit_ttl_minutes = permit_ttl_minutes
        self._allowed_tools: list[str] | None = (
            [_validate_identifier(t, "tool name") for t in allowed_tools]
            if allowed_tools is not None
            else None
        )
        self._key_store_path = Path(key_store_path) if key_store_path else None
        # Cache permits to avoid 409 on replay (server hashes full permit body including expires_at)
        self._permit_cache: dict[str, str] = {}  # permit_idempotency_key → permit_id
        self._permit_requests: dict[str, PermitRequest] = {}
        if self._key_store_path is not None:
            self._load_key_store()

    def register_tool(self, tool_name: str) -> str:
        """Allow one MCP tool name for :meth:`call_mcp_tool`.

        Returns the registered name so call sites read plainly.
        """
        _validate_identifier(tool_name, "tool name")
        if self._allowed_tools is None:
            self._allowed_tools = []
        if tool_name not in self._allowed_tools:
            self._allowed_tools.append(tool_name)
        return tool_name

    def _require_tool_allowed(self, tool_name: str) -> str:
        _validate_identifier(tool_name, "tool name")
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            raise ValueError(f"tool {tool_name!r} is not registered")
        return tool_name

    def _load_key_store(self) -> None:
        assert self._key_store_path is not None
        if not self._key_store_path.exists():
            return
        data = json.loads(self._key_store_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            raise TypeError(f"{self._key_store_path}: key store must be a JSON object")
        for key, entry in data.get("permits", {}).items():
            if not isinstance(entry, dict) or "request" not in entry:
                continue
            payload = dict(entry["request"])
            payload["max_credits"] = Decimal(payload["max_credits"])
            payload["expires_at"] = datetime.fromisoformat(payload["expires_at"])
            self._permit_requests[key] = PermitRequest(**payload)
            if entry.get("permit_id") is not None:
                self._permit_cache[key] = entry["permit_id"]

    def _save_key_store(self) -> None:
        if self._key_store_path is None:
            return
        data = {
            "permits": {
                key: {
                    "permit_id": self._permit_cache.get(key),
                    "request": request.to_payload(),
                }
                for key, request in self._permit_requests.items()
            }
        }
        self._key_store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._key_store_path.parent,
            prefix=self._key_store_path.name,
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._key_store_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Discover all available MCP tools."""
        tools = await self.client.discover_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    async def call_mcp_tool(
        self,
        tool_name: str,
        idempotency_key: str,
        permit_idempotency_key: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call an MCP tool via governed permit→invoke→receipt flow.

        Args:
            tool_name: Name of the tool to call
            idempotency_key: Caller-supplied idempotency key (required)
            permit_idempotency_key: Caller-supplied permit idempotency key (required)
            arguments: Tool arguments
        """
        if arguments is None:
            arguments = {}
        _validate_identifier(idempotency_key, "idempotency_key")
        _validate_identifier(permit_idempotency_key, "permit_idempotency_key")
        self._require_tool_allowed(tool_name)

        # Retain the body before the first await: a lost acknowledgement must
        # replay the original expiry under the same caller-owned key.
        request = self._permit_requests.get(permit_idempotency_key)
        if request is None:
            request = PermitRequest(
                issuer_wallet_id=self.wallet_id,
                subject_wallet_id=self.wallet_id,
                max_credits=self.permit_budget,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=self.permit_ttl_minutes),
                allowed_tools=[tool_name],
                scopes=[f"tool:{tool_name}:invoke", "billing:charge"],
            )
            self._permit_requests[permit_idempotency_key] = request
            self._save_key_store()
        elif (
            request.subject_wallet_id != self.wallet_id
            or request.max_credits != self.permit_budget
            or request.allowed_tools != [tool_name]
        ):
            raise ValueError(
                "permit_idempotency_key reused with different permit terms"
            )

        if permit_idempotency_key in self._permit_cache:
            permit_id = self._permit_cache[permit_idempotency_key]
        else:
            permit = await self.client.create_permit(
                request, idempotency_key=permit_idempotency_key
            )
            permit_id = permit.permit_id
            self._permit_cache[permit_idempotency_key] = permit_id
            self._save_key_store()

        result = await self.client.invoke_tool(
            tool_name,
            arguments,
            wallet_id=self.wallet_id,
            permit_id=permit_id,
            idempotency_key=idempotency_key,
        )

        return {
            "content": result.content,
            "structured_content": result.structured_content,
            "receipt_id": result.receipt.receipt_id,
            "credits_charged": str(result.receipt.credits_charged),
            "signature": result.receipt.signature,
        }

    async def get_wallet_balance(self) -> float:
        """Get current wallet balance."""
        return await self.client.get_balance(self.wallet_id)

    def get_function_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI function schemas for all available operations."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "discover_tools",
                    "description": "Discover all available MCP tools from Agent Middleware API",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_mcp_tool",
                    "description": "Call a specific MCP tool via governed permit→invoke→receipt flow. Returns signed receipt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool_name": {
                                "type": "string",
                                "description": "Name of the MCP tool to call",
                            },
                            "idempotency_key": {
                                "type": "string",
                                "description": "Caller-supplied idempotency key (required, must be unique per invocation)",
                            },
                            "permit_idempotency_key": {
                                "type": "string",
                                "description": "Caller-supplied permit idempotency key (required, must be stable for replay)",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Arguments to pass to the tool",
                            },
                        },
                        "required": [
                            "tool_name",
                            "idempotency_key",
                            "permit_idempotency_key",
                        ],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_wallet_balance",
                    "description": "Get the current wallet balance in credits",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]


def register_b2a_tools(agent: ConversableAgent, b2a_tool: B2AFunctionTool) -> None:
    """Register B2A tools with an AutoGen agent.

    Args:
        agent: AutoGen ConversableAgent instance
        b2a_tool: B2AFunctionTool instance configured with API credentials
    """
    function_schemas = b2a_tool.get_function_schemas()
    for schema in function_schemas:
        agent.register_function(
            function_map={
                schema["function"]["name"]: getattr(
                    b2a_tool, schema["function"]["name"]
                ),
            }
        )
