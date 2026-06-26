"""Shared HTTP edge client for framework wrappers.

The framework wrappers (langchain, crewai, autogen) all need the same
narrow surface: list MCP tools, call an MCP tool, drive an AWI session, read
a wallet balance. This base centralizes that surface so each wrapper only has
to add the framework-specific glue.

This is intentionally a smaller surface than ``B2AClient``. ``B2AClient`` is
the full agent-facing client used by service code and decorators; this base
is the wrapper-facing edge client used by framework integrations that just
need to talk to the middleware over HTTP.
"""

from __future__ import annotations

from typing import Any

import httpx


class B2AEdgeClient:
    """Shared async HTTP surface for framework wrappers.

    Subclasses can override or extend specific methods to add
    framework-specific affordances (e.g. returning langchain ``Tool`` objects
    instead of raw dicts) without re-implementing the HTTP plumbing.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        api_key: str | None = None,
        wallet_id: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.wallet_id = wallet_id
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    def _auth_headers(self) -> dict[str, str]:
        """Bare auth headers for requests with no body (GET)."""
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _headers(self) -> dict[str, str]:
        """Auth + JSON headers for requests with a body (POST/PUT/PATCH)."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def get_mcp_tools(self) -> list[dict[str, Any]]:
        """Fetch available MCP tools from the server."""
        response = await self._client.get(
            f"{self.api_url}/mcp/tools.json",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("tools", [])

    async def call_mcp_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool by name."""
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
            "id": 1,
        }
        if self.wallet_id:
            payload["params"]["mcpContext"] = {"wallet_id": self.wallet_id}

        response = await self._client.post(
            f"{self.api_url}/mcp/messages",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def create_awi_session(
        self,
        target_url: str,
        max_steps: int = 100,
    ) -> dict[str, Any]:
        """Create an AWI session for web interaction."""
        payload = {"target_url": target_url, "max_steps": max_steps}
        response = await self._client.post(
            f"{self.api_url}/v1/awi/sessions",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def execute_awi_action(
        self,
        session_id: str,
        action: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an AWI action on a session."""
        payload = {
            "session_id": session_id,
            "action": action,
            "parameters": parameters,
        }
        response = await self._client.post(
            f"{self.api_url}/v1/awi/execute",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_balance(self) -> float:
        """Get wallet balance. Requires ``wallet_id`` set on the client."""
        if not self.wallet_id:
            raise ValueError("wallet_id required for balance check")
        response = await self._client.get(
            f"{self.api_url}/v1/billing/wallets/{self.wallet_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("balance", 0.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> B2AEdgeClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
