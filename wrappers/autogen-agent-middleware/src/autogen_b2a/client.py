"""B2A Client for AutoGen integration."""

from typing import Any
import httpx


class B2AClient:
    """Client for Agent Middleware API with AutoGen compatibility."""

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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def get_mcp_tools(self) -> list[dict[str, Any]]:
        """Fetch available MCP tools."""
        response = await self._client.get(
            f"{self.api_url}/mcp/tools.json",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json().get("tools", [])

    async def call_mcp_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool."""
        payload = {
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
        """Create an AWI session."""
        payload = {"target_url": target_url, "max_steps": max_steps}
        response = await self._client.post(
            f"{self.api_url}/v1/awi/sessions",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_balance(self) -> float:
        """Get wallet balance."""
        if not self.wallet_id:
            raise ValueError("wallet_id required")
        response = await self._client.get(
            f"{self.api_url}/v1/billing/wallets/{self.wallet_id}",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json().get("balance", 0.0)

    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
