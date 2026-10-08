"""
AWI Python SDK Client — Phase 8
===============================
Lightweight client for interacting with AWI-enabled services.

Based on arXiv:2506.10953v1 - "Build the web for agents, not agents for the web"

Proof surface note: the ``/v1/awi/*`` routes this client calls are frozen
proof surfaces. Production-like deployments leave them unmounted
(``ENABLE_PROOF_SURFACES=false``), so this client only works against a
server started with proof surfaces enabled. See ``docs/PROOF_SURFACES.md``.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import errors as _errors
from .models import AWIActionDefinition, AWIExecutionResponse

#: Longest ``Idempotency-Key`` the governed AWI routes accept.
MAX_IDEMPOTENCY_KEY_LENGTH = 128

#: Statuses worth one more attempt under the same idempotency key.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 502, 503, 504})


@dataclass
class AWIClientConfig:
    """Configuration for AWI client."""

    base_url: str = "http://localhost:8000"
    # Kept out of repr() so logging a config never prints the credential.
    api_key: str | None = field(default=None, repr=False)
    wallet_id: str | None = None
    timeout: float = 30.0
    # Retries after the first attempt for transport failures and the
    # retryable statuses above. Governed calls reuse the caller's
    # idempotency key on every attempt, so the server replays the first
    # outcome instead of acting twice.
    max_retries: int = 3

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")


class AWIClient:
    """
    Python client for AWI (Agentic Web Interface) services.

    Provides a clean interface for agents to interact with AWI-enabled websites
    using standardized actions and progressive representations.

    Example:
        client = AWIClient(
            base_url="https://api.example.com",
            api_key="your-key",
            wallet_id="wallet-123"
        )

        session = await client.create_session("https://shop.example.com")
        result = await client.execute(
            session["session_id"],
            "search_and_sort",
            {"query": "laptops", "sort_by": "price"},
            permit_id="permit-from-POST-/v1/permits",
            idempotency_key="search-laptops-1",
        )
    """

    def __init__(self, config: AWIClientConfig | None = None, **kwargs):
        if config is None:
            config = AWIClientConfig(**kwargs)
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout,
            headers=self._build_headers(),
            # A redirect must not carry X-API-Key to another host.
            follow_redirects=False,
        )

    def _build_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        return headers

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send one request with retries and typed errors.

        Retries transport failures and retryable statuses up to
        ``config.max_retries`` times after the first attempt, with a small
        linear backoff. Client errors (400-404, 409 conflicts, permit
        refusals) are never retried. Error responses raise the matching
        :mod:`awi_sdk.errors` type.
        """
        attempts = self.config.max_retries + 1
        last_transport_error: httpx.TransportError | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            if response.status_code in RETRYABLE_STATUS_CODES and attempt + 1 < attempts:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            _errors.raise_for_status(response)
            return response
        assert last_transport_error is not None  # for type checkers
        raise last_transport_error

    async def discover(self) -> dict[str, Any]:
        """
        Discover AWI capabilities from the server.

        Returns the manifest with available actions and representations.
        """
        response = await self._request("GET", "/v1/awi/vocabulary")
        return response.json()

    async def create_session(
        self,
        target_url: str,
        max_steps: int = 100,
        allow_human_pause: bool = True,
    ) -> dict[str, Any]:
        """
        Create a new AWI session.

        Args:
            target_url: URL of the AWI-enabled website
            max_steps: Maximum number of actions in this session
            allow_human_pause: Allow humans to pause the session

        Returns:
            Session object with session_id and metadata
        """
        response = await self._request(
            "POST",
            "/v1/awi/sessions",
            json={
                "target_url": target_url,
                "max_steps": max_steps,
                "allow_human_pause": allow_human_pause,
                "wallet_id": self.config.wallet_id,
            },
        )
        return response.json()

    async def execute(
        self,
        session_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        representation: str | None = None,
        dry_run: bool = False,
        *,
        permit_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        Execute an AWI action within a session.

        ``POST /v1/awi/execute`` is governed: it requires a signed permit for
        tool ``awi_execute`` and an idempotency key, sent as ``X-Permit-Id``
        and ``Idempotency-Key``. Reuse the same key when retrying one logical
        action so the server replays the first outcome instead of acting twice.

        Args:
            session_id: ID of the active session
            action: Standardized action name (e.g., "search_and_sort")
            parameters: Action-specific parameters
            representation: Request a specific representation after
            dry_run: Simulate without side effects
            permit_id: Permit authorizing ``awi_execute`` for this wallet
            idempotency_key: Caller-chosen key for this logical action
                (non-blank, at most 128 characters)

        Returns:
            Execution result with status, output, and optional representation

        Raises:
            ValueError: ``permit_id`` or ``idempotency_key`` is unusable; no
                request is sent.
        """
        headers = self._governed_headers(permit_id, idempotency_key)
        payload = {
            "session_id": session_id,
            "action": action,
            "parameters": parameters or {},
            "dry_run": dry_run,
        }
        if representation:
            payload["representation_request"] = representation

        response = await self._request("POST", "/v1/awi/execute", json=payload, headers=headers)
        return response.json()

    async def execute_typed(
        self,
        session_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        representation: str | None = None,
        dry_run: bool = False,
        *,
        permit_id: str,
        idempotency_key: str,
    ) -> AWIExecutionResponse:
        """Execute an action and return the typed response model.

        Same request as :meth:`execute`, but the body is parsed into
        :class:`AWIExecutionResponse`. Callers that need the full server
        envelope (receipt, ledger entries) should use :meth:`execute`.
        """
        raw = await self.execute(
            session_id,
            action,
            parameters,
            representation,
            dry_run,
            permit_id=permit_id,
            idempotency_key=idempotency_key,
        )
        return AWIExecutionResponse.from_dict(raw)

    @staticmethod
    def _governed_headers(permit_id: str, idempotency_key: str) -> dict[str, str]:
        """Validate and build the governance headers for a governed route."""
        permit = permit_id.strip() if isinstance(permit_id, str) else ""
        if not permit:
            raise ValueError("permit_id must not be blank")
        key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
        if not key:
            raise ValueError("idempotency_key must not be blank")
        if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ValueError(
                f"idempotency_key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            )
        return {"X-Permit-Id": permit, "Idempotency-Key": key}

    async def get_representation(
        self,
        session_id: str,
        representation_type: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Request a specific representation of the current session state.

        Args:
            session_id: ID of the active session
            representation_type: Type of representation (summary, embedding, etc.)
            options: Representation-specific options

        Returns:
            Representation content and metadata
        """
        response = await self._request(
            "POST",
            "/v1/awi/represent",
            json={
                "session_id": session_id,
                "representation_type": representation_type,
                "options": options or {},
            },
        )
        return response.json()

    async def pause(self, session_id: str, reason: str | None = None) -> dict[str, Any]:
        """Pause an AWI session for human review."""
        response = await self._request(
            "POST",
            "/v1/awi/intervene",
            json={
                "session_id": session_id,
                "action": "pause",
                "reason": reason,
            },
        )
        return response.json()

    async def resume(self, session_id: str) -> dict[str, Any]:
        """Resume a paused AWI session."""
        response = await self._request(
            "POST",
            "/v1/awi/intervene",
            json={
                "session_id": session_id,
                "action": "resume",
            },
        )
        return response.json()

    async def steer(self, session_id: str, instructions: str) -> dict[str, Any]:
        """Steer an AWI session with new instructions."""
        response = await self._request(
            "POST",
            "/v1/awi/intervene",
            json={
                "session_id": session_id,
                "action": "steer",
                "steer_instructions": instructions,
            },
        )
        return response.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Get the current state of a session."""
        response = await self._request("GET", f"/v1/awi/sessions/{session_id}")
        return response.json()

    async def destroy_session(self, session_id: str) -> None:
        """Destroy an AWI session."""
        await self._request("DELETE", f"/v1/awi/sessions/{session_id}")

    async def create_task(
        self,
        task_type: str,
        target_url: str,
        action_sequence: list[dict[str, Any]],
        priority: int = 5,
    ) -> dict[str, Any]:
        """Create a queued AWI task."""
        response = await self._request(
            "POST",
            "/v1/awi/tasks",
            json={
                "task_type": task_type,
                "target_url": target_url,
                "action_sequence": action_sequence,
                "priority": priority,
            },
        )
        return response.json()

    async def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Get the status of an AWI task."""
        response = await self._request("GET", f"/v1/awi/tasks/{task_id}")
        return response.json()

    async def get_queue_status(self) -> dict[str, Any]:
        """Get the overall task queue status."""
        response = await self._request("GET", "/v1/awi/queue/status")
        return response.json()

    async def list_actions(self) -> list[dict[str, Any]]:
        """List all available AWI actions as raw dicts."""
        vocab = await self.discover()
        return vocab.get("actions", [])

    async def list_actions_by_category(self, category: str) -> list[dict[str, Any]]:
        """List AWI actions in a specific category as raw dicts."""
        response = await self._request("GET", f"/v1/awi/vocabulary/category/{category}")
        return response.json().get("actions", [])

    async def list_action_definitions(self) -> list[AWIActionDefinition]:
        """List all available AWI actions as typed definitions."""
        return [AWIActionDefinition.from_dict(a) for a in await self.list_actions()]

    async def list_action_definitions_by_category(self, category: str) -> list[AWIActionDefinition]:
        """List AWI actions in a specific category as typed definitions."""
        return [
            AWIActionDefinition.from_dict(a) for a in await self.list_actions_by_category(category)
        ]
