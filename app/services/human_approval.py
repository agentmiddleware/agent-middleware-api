"""Human approval gate for governed invokes, backed by Sentinel (pauseapi.app).

A permit created with ``requires_human_approval=true`` makes every governed
invoke under it block on a human decision before any budget is reserved or
credits are charged. The decision itself lives in Sentinel; this module keeps a
local ``human_approvals`` row per invoke attempt so retries with the same
idempotency key re-check the same approval instead of paging a human again.

Sentinel contract notes that shape this module (see docs/human-approval-gate.md):

- ``POST /v1/approvals`` authenticates with ``Authorization: Bearer sk_...``,
  supports an ``Idempotency-Key`` header, and returns ``action_id`` with
  ``status="pending"``.
- ``GET /v1/approvals/{id}/wait?timeout=N`` long-polls (1..300s) and returns
  the still-pending approval with HTTP 200 on timeout — callers must check
  ``status``.
- Sentinel has **no** expired state: a timed-out approval stays "pending"
  forever, and ``timeout_seconds`` only bounds the magic-link tokens. The
  middleware therefore enforces ``expires_at`` locally and treats a decision
  arriving after local expiry as too late.

Fail-closed posture:

- Simulation mode auto-approves (marked ``simulated``) in local/dev
  environments only. In a production-like environment a simulated approval is
  never honored — the gate denies with ``human_approval_not_configured``.
- Real mode without ``SENTINEL_API_URL``/``SENTINEL_API_KEY`` denies the same
  way.
- Sentinel being unreachable raises ``HumanApprovalUnavailableError`` — a
  retryable condition the router surfaces without consuming the caller's
  idempotency key, so the invoke can be retried once Sentinel recovers.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.runtime_mode import is_simulation
from app.core.time import utc_now
from app.core.trust_mode import is_production_like_environment
from app.db.database import get_session_factory
from app.db.models import HumanApprovalModel

logger = logging.getLogger(__name__)

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_REJECTED = "rejected"
APPROVAL_STATUS_EXPIRED = "expired"

# Sentinel bounds: timeout_seconds 1..86400, /wait timeout 1..300.
_SENTINEL_TIMEOUT_MIN = 1
_SENTINEL_TIMEOUT_MAX = 86400
_SENTINEL_WAIT_MAX = 300.0
_HTTP_TIMEOUT_SECONDS = 10.0


class HumanApprovalError(Exception):
    """Terminal gate failure; ``reason`` is the receipt/audit denial reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HumanApprovalUnavailableError(Exception):
    """Sentinel could not be reached; the invoke may be retried later."""

    def __init__(self, reason: str = "human_approval_unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ApprovalCheck:
    """Outcome of one gate evaluation for a governed invoke."""

    status: str  # pending | approved | rejected | expired
    approval_id: str
    sentinel_action_id: str | None
    simulated: bool
    decided_by: str | None
    reason: str | None
    expires_at: Any  # datetime; naive UTC


def human_approval_configured() -> bool:
    """Whether real-mode Sentinel calls are possible with current settings."""
    settings = get_settings()
    return bool(
        (settings.SENTINEL_API_URL or "").strip()
        and (settings.SENTINEL_API_KEY or "").strip()
    )


def human_approval_available() -> tuple[bool, str | None]:
    """Whether a requires_human_approval permit can be honored right now.

    Returns ``(True, None)`` when the gate can produce real approvals, or
    simulated ones in an environment where that is acceptable. Otherwise
    ``(False, reason)`` — the same reason the invoke-time gate would deny with,
    so permit creation can fail early instead of minting a permit that every
    invoke rejects.
    """
    settings = get_settings()
    if is_simulation("human_approval"):
        if is_production_like_environment(settings.ENVIRONMENT):
            return False, "human_approval_not_configured"
        return True, None
    if not human_approval_configured():
        return False, "human_approval_not_configured"
    return True, None


class SentinelClient:
    """Thin async client for the Sentinel approvals API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_approval(
        self,
        *,
        function_name: str,
        arguments: dict[str, Any],
        risk_level: str,
        approvers: list[str],
        timeout_seconds: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key[:255]}
        body: dict[str, Any] = {
            "function_name": function_name,
            "arguments": arguments,
            "risk_level": risk_level,
            "timeout_seconds": timeout_seconds,
        }
        if approvers:
            body["approvers"] = approvers
        resp = await self.client.post("/v1/approvals", json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def get_approval(self, action_id: str) -> dict[str, Any]:
        resp = await self.client.get(f"/v1/approvals/{action_id}")
        resp.raise_for_status()
        return resp.json()

    async def wait_approval(self, action_id: str, timeout: float) -> dict[str, Any]:
        # Sentinel clamps /wait to 1..300s and returns the still-pending
        # approval with 200 on timeout.
        bounded = max(1.0, min(timeout, _SENTINEL_WAIT_MAX))
        resp = await self.client.get(
            f"/v1/approvals/{action_id}/wait",
            params={"timeout": bounded},
            # The HTTP read must outlive the server-side long-poll window.
            timeout=bounded + _HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()


class HumanApprovalService:
    """Evaluate and persist the human-approval gate for governed invokes."""

    def __init__(self) -> None:
        self._client: SentinelClient | None = None

    def _sentinel(self) -> SentinelClient:
        settings = get_settings()
        if self._client is None:
            self._client = SentinelClient(
                settings.SENTINEL_API_URL, settings.SENTINEL_API_KEY
            )
        return self._client

    @staticmethod
    def _timeout_seconds() -> int:
        raw = get_settings().SENTINEL_APPROVAL_TIMEOUT_SECONDS
        return max(_SENTINEL_TIMEOUT_MIN, min(int(raw), _SENTINEL_TIMEOUT_MAX))

    @staticmethod
    def _approvers() -> list[str]:
        raw = get_settings().SENTINEL_APPROVERS or ""
        return [entry.strip() for entry in raw.split(",") if entry.strip()]

    @staticmethod
    def _check(model: HumanApprovalModel) -> ApprovalCheck:
        return ApprovalCheck(
            status=model.status,
            approval_id=model.approval_id,
            sentinel_action_id=model.sentinel_action_id,
            simulated=model.simulated,
            decided_by=model.decided_by,
            reason=model.reason,
            expires_at=model.expires_at,
        )

    async def _load(
        self,
        *,
        wallet_id: str,
        permit_id: str,
        tool_name: str,
        idempotency_key: str,
    ) -> HumanApprovalModel | None:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(HumanApprovalModel).where(
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.wallet_id == wallet_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.permit_id == permit_id,
                    ),
                    cast(ColumnElement[bool], HumanApprovalModel.tool == tool_name),
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.idempotency_key == idempotency_key,
                    ),
                )
            )
            return result.scalar_one_or_none()

    @staticmethod
    def _apply_decision(
        model: HumanApprovalModel, payload: dict[str, Any]
    ) -> None:
        status = payload.get("status") or payload.get("decision") or ""
        if status in {APPROVAL_STATUS_APPROVED, APPROVAL_STATUS_REJECTED}:
            model.status = status
            model.decided_by = payload.get("decided_by")
            model.reason = payload.get("reason")
            model.decided_at = utc_now()

    async def _persist(self, model: HumanApprovalModel) -> None:
        factory = get_session_factory()
        async with factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)

    async def ensure_approval(
        self,
        *,
        wallet_id: str,
        permit_id: str,
        tool_name: str,
        idempotency_key: str,
        arguments: dict[str, Any],
        estimated_credits: Any,
    ) -> ApprovalCheck:
        """Return the current approval state for one governed invoke attempt.

        Creates the approval (locally, and in Sentinel in real mode) on first
        sight of this (wallet, permit, tool, idempotency_key); re-checks the
        stored one on retries. Local expiry is enforced before any remote
        poll, because Sentinel never expires approvals server-side.

        Raises ``HumanApprovalError`` for terminal misconfiguration and
        ``HumanApprovalUnavailableError`` when Sentinel cannot be reached.
        """
        settings = get_settings()
        simulated = is_simulation("human_approval")
        production_like = is_production_like_environment(settings.ENVIRONMENT)

        # A simulated approval must never authorize a production invoke.
        if simulated and production_like:
            raise HumanApprovalError("human_approval_not_configured")
        if not simulated and not human_approval_configured():
            raise HumanApprovalError("human_approval_not_configured")

        model = await self._load(
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
        )
        if model is not None:
            return await self._refresh(model)

        now = utc_now()
        expires_at = now + timedelta(seconds=self._timeout_seconds())
        model = HumanApprovalModel(
            approval_id=f"appr-{uuid.uuid4().hex[:16]}",
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool=tool_name,
            idempotency_key=idempotency_key,
            status=APPROVAL_STATUS_PENDING,
            simulated=simulated,
            requested_at=now,
            expires_at=expires_at,
        )

        if simulated:
            # Local/dev only (production-like was rejected above): approve
            # instantly, clearly marked, so demo loops stay self-contained.
            model.status = APPROVAL_STATUS_APPROVED
            model.decided_by = "simulation"
            model.reason = "simulated_auto_approval"
            model.decided_at = now
            await self._persist_new(model)
            return self._check(model)

        remote = await self._create_remote(model, arguments, estimated_credits)
        self._apply_decision(model, remote)

        if model.status == APPROVAL_STATUS_PENDING:
            wait_seconds = float(settings.SENTINEL_WAIT_SECONDS or 0)
            if wait_seconds > 0 and model.sentinel_action_id:
                try:
                    waited = await self._sentinel().wait_approval(
                        model.sentinel_action_id, wait_seconds
                    )
                    self._apply_decision(model, waited)
                except httpx.HTTPError as exc:
                    # The approval exists; a failed wait is not fatal.
                    logger.warning("sentinel_wait_failed: %s", exc)

        await self._persist_new(model)
        return self._check(model)

    async def _persist_new(self, model: HumanApprovalModel) -> None:
        try:
            await self._persist(model)
        except IntegrityError:
            # Concurrent first-invoke race: another worker inserted the row.
            # Sentinel-side duplication is prevented by the Idempotency-Key on
            # create. Fall back to the winner's row.
            existing = await self._load(
                wallet_id=model.wallet_id,
                permit_id=model.permit_id,
                tool_name=model.tool,
                idempotency_key=model.idempotency_key,
            )
            if existing is None:  # pragma: no cover - repair path
                raise
            model.approval_id = existing.approval_id
            model.status = existing.status

    async def _create_remote(
        self,
        model: HumanApprovalModel,
        arguments: dict[str, Any],
        estimated_credits: Any,
    ) -> dict[str, Any]:
        settings = get_settings()
        try:
            payload = await self._sentinel().create_approval(
                function_name=model.tool,
                arguments={
                    "tool": model.tool,
                    "arguments": arguments,
                    "wallet_id": model.wallet_id,
                    "permit_id": model.permit_id,
                    "estimated_credits": str(estimated_credits),
                    "middleware": settings.PUBLIC_URL or "agent-middleware-api",
                },
                risk_level=settings.SENTINEL_RISK_LEVEL or "high",
                approvers=self._approvers(),
                timeout_seconds=self._timeout_seconds(),
                idempotency_key=f"mw-{model.approval_id}",
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if 400 <= status_code < 500:
                # Misconfiguration (bad key, no approvers, bad risk level):
                # terminal — retrying without an operator fix cannot succeed.
                logger.error(
                    "sentinel_create_rejected status=%s body=%s",
                    status_code,
                    exc.response.text[:500],
                )
                raise HumanApprovalError("human_approval_request_rejected") from exc
            raise HumanApprovalUnavailableError() from exc
        except httpx.HTTPError as exc:
            raise HumanApprovalUnavailableError() from exc

        action_id = payload.get("action_id") or payload.get("id")
        if not action_id:
            logger.error("sentinel_create_malformed_response: %s", payload)
            raise HumanApprovalUnavailableError()
        model.sentinel_action_id = str(action_id)
        return payload

    async def _refresh(self, model: HumanApprovalModel) -> ApprovalCheck:
        """Re-evaluate a stored approval: local expiry first, then Sentinel."""
        if model.status != APPROVAL_STATUS_PENDING:
            return self._check(model)

        if utc_now() >= model.expires_at:
            model.status = APPROVAL_STATUS_EXPIRED
            model.reason = "approval_window_elapsed"
            model.decided_at = utc_now()
            await self._persist(model)
            return self._check(model)

        if model.simulated:  # pragma: no cover - simulated rows decide at create
            return self._check(model)

        if not model.sentinel_action_id:
            raise HumanApprovalUnavailableError()

        try:
            payload = await self._sentinel().get_approval(model.sentinel_action_id)
        except httpx.HTTPError as exc:
            raise HumanApprovalUnavailableError() from exc

        self._apply_decision(model, payload)
        if model.status != APPROVAL_STATUS_PENDING:
            # A decision that lands after local expiry is too late: the
            # expiry check above already ran, so reaching here means the
            # decision arrived in time.
            await self._persist(model)
        return self._check(model)


_service: HumanApprovalService | None = None


def get_human_approval_service() -> HumanApprovalService:
    global _service
    if _service is None:
        _service = HumanApprovalService()
    return _service
