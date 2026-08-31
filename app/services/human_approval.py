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
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.runtime_mode import is_simulation
from app.core.time import to_naive_utc
from app.core.trust_mode import is_production_like_environment
from app.db.database import get_session_factory
from app.db.models import HumanApprovalModel
from app.services.signing_keys import sha256_hex

logger = logging.getLogger(__name__)

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_REJECTED = "rejected"
APPROVAL_STATUS_EXPIRED = "expired"
# Terminal single-use state: an approved approval that has already authorized
# one governed invoke. Reached only via the atomic consume in the gate, so a
# second invoke (e.g. the other transport, or a stale retry) cannot re-spend it.
APPROVAL_STATUS_CONSUMED = "consumed"
# Raised when a reloaded approval no longer matches the invoke being attempted.
APPROVAL_REASON_MISMATCH = "human_approval_request_mismatch"

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

    status: str  # pending | approved | rejected | expired | consumed
    approval_id: str
    sentinel_action_id: str | None
    simulated: bool
    decided_by: str | None
    reason: str | None
    expires_at: Any  # datetime; naive UTC


def invoke_request_hash(
    tool_name: str,
    arguments: dict[str, Any],
    estimated_credits: Any,
) -> str:
    """Bind an approval to the exact call the human reviewed.

    The human approves a specific ``(tool, arguments, estimated_credits)``
    request in Sentinel; the stored approval carries this hash so a later
    invoke that reuses the same idempotency key with different arguments or a
    different current price cannot ride the approval. Uses the same
    canonical-JSON hash as the signing layer so ordering/formatting can't be
    used to forge a match.
    """
    return sha256_hex(
        {
            "tool": tool_name,
            "arguments": arguments,
            "estimated_credits": estimated_credits,
        }
    )


def sentinel_idempotency_key(
    wallet_id: str,
    permit_id: str,
    tool_name: str,
    idempotency_key: str,
    request_hash: str,
) -> str:
    """Deterministic Sentinel Idempotency-Key for one governed invoke.

    Derived from the invoke identity — NOT from the per-attempt random
    approval_id — so every retry and every concurrent worker for the *same*
    invoke sends the same key. Sentinel dedups on (tenant, key), so this is
    what makes a network-lost create or a concurrent first invoke resolve to a
    single approval and page the human exactly once.

    ``request_hash`` (the bound tool, arguments, and estimated credits) is part
    of the key so a retry with the same idempotency key but different reviewed
    details gets a different key and a separate Sentinel approval. Without it,
    if Sentinel committed the first create but the response was lost before
    the local binding row was written, a changed-arguments or changed-price
    retry would dedup onto the original approval and later bind the retry's
    hash to the human's original decision.
    """
    digest = sha256_hex(
        {
            "wallet_id": wallet_id,
            "permit_id": permit_id,
            "tool": tool_name,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
        }
    )
    return f"mw-{digest[:48]}"


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


def _decode_json(resp: httpx.Response) -> dict[str, Any]:
    """Parse a Sentinel 2xx body, treating a non-JSON payload as an outage.

    A gateway/LB can return a 200 with an HTML error page; ``resp.json()``
    then raises ``ValueError`` (``json.JSONDecodeError``), which is NOT an
    ``httpx.HTTPError``. Left unconverted it would escape the gate's
    error handling and strand the caller's idempotency record in-progress
    forever. Map it to the retryable unavailable path instead.
    """
    try:
        body = resp.json()
    except ValueError as exc:
        raise HumanApprovalUnavailableError() from exc
    if not isinstance(body, dict):
        raise HumanApprovalUnavailableError()
    return body


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
        return _decode_json(resp)

    async def get_approval(self, action_id: str) -> dict[str, Any]:
        resp = await self.client.get(f"/v1/approvals/{action_id}")
        resp.raise_for_status()
        return _decode_json(resp)

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
        return _decode_json(resp)


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
    def _database_utc_now_expression(
        session: Any,
    ) -> ColumnElement[Any]:
        """Return a naive-UTC database clock expression for this dialect."""
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            return cast(
                ColumnElement[Any],
                func.timezone("UTC", func.statement_timestamp()),
            )
        if dialect == "sqlite":
            # SQLite's ``%f`` has millisecond precision; append zeros so the
            # fixed-width value matches the microsecond storage convention.
            return cast(
                ColumnElement[Any],
                func.strftime("%Y-%m-%d %H:%M:%f000", "now"),
            )
        return cast(ColumnElement[Any], func.current_timestamp())

    async def _database_utc_now(self) -> datetime:
        factory = get_session_factory()
        async with factory() as session:
            value = await session.scalar(
                select(self._database_utc_now_expression(session))
            )
        if isinstance(value, datetime):
            return to_naive_utc(value)
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise HumanApprovalUnavailableError()

    @staticmethod
    def _apply_decision(model: HumanApprovalModel, payload: dict[str, Any]) -> None:
        """Parse Sentinel's decision; the database authors its timestamp."""
        status = payload.get("status") or payload.get("decision") or ""
        if status in {APPROVAL_STATUS_APPROVED, APPROVAL_STATUS_REJECTED}:
            model.status = status
            model.decided_by = payload.get("decided_by")
            model.reason = payload.get("reason")

    async def _persist(self, model: HumanApprovalModel) -> None:
        factory = get_session_factory()
        async with factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)

    async def _expire_if_stale(self, model: HumanApprovalModel) -> bool:
        """Best-effort label a still-pending, past-window approval as expired.

        Conditional on ``status='pending'`` and the database row's deadline so
        it can never clobber an approved, consumed, or still-live decision.
        """
        factory = get_session_factory()
        async with factory() as session:
            database_now = self._database_utc_now_expression(session)
            result = await session.execute(
                update(HumanApprovalModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.approval_id == model.approval_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.status == APPROVAL_STATUS_PENDING,
                    ),
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.expires_at <= database_now,
                    ),
                )
                .values(
                    status=APPROVAL_STATUS_EXPIRED,
                    reason="approval_window_elapsed",
                    decided_at=database_now,
                )
            )
            await session.commit()
            return bool(cast(Any, result).rowcount)

    async def _consume(self, approval_id: str) -> bool:
        """Atomically spend an observed approved authority — single use.

        The one place a governed invoke is authorized to move money. The
        guarded update is the serialization point for the same key over both
        transports and concurrent retries. A decision may be consumed after
        its review window only when durable timestamps prove it was observed
        after the request and before the deadline. Exactly one caller can
        advance that authority to ``consumed``.
        """
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                update(HumanApprovalModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.approval_id == approval_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.status == APPROVAL_STATUS_APPROVED,
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, HumanApprovalModel.decided_at).is_not(None),
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, HumanApprovalModel.requested_at)
                        <= cast(Any, HumanApprovalModel.decided_at),
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, HumanApprovalModel.decided_at)
                        < cast(Any, HumanApprovalModel.expires_at),
                    ),
                )
                # Preserve decided_at (the human decision time) — only the
                # status transitions to consumed.
                .values(status=APPROVAL_STATUS_CONSUMED)
            )
            await session.commit()
            return cast(Any, result).rowcount == 1

    async def ensure_approval(
        self,
        *,
        wallet_id: str,
        permit_id: str,
        tool_name: str,
        idempotency_key: str,
        arguments: dict[str, Any],
        estimated_credits: Any,
        consume_immediately: bool = True,
    ) -> ApprovalCheck:
        """Return the current approval state for one governed invoke attempt.

        Creates the approval (locally, and in Sentinel in real mode) on first
        sight of this (wallet, permit, tool, idempotency_key); re-checks the
        stored one on retries. By default, an APPROVED decision is atomically
        consumed here. Remote dispatch passes ``consume_immediately=False`` so
        approval consumption can commit in the same transaction as permit
        reservation and durable dispatch preparation.

        Raises ``HumanApprovalError`` for terminal misconfiguration/mismatch
        and ``HumanApprovalUnavailableError`` when Sentinel cannot be reached.
        """
        settings = get_settings()
        simulated = is_simulation("human_approval")
        production_like = is_production_like_environment(settings.ENVIRONMENT)
        req_hash = invoke_request_hash(tool_name, arguments, estimated_credits)

        # Fresh-create config guards (current environment).
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
            self._reauthorize(model, req_hash=req_hash, production_like=production_like)
            if (
                model.status == APPROVAL_STATUS_PENDING
                and not model.simulated
                and not model.sentinel_action_id
            ):
                # A worker may have died after persisting intent but before
                # provider create/binding. Expire from the database clock
                # before reissuing create so a dead authority never pages a
                # human or reports a misleading pending state.
                await self._expire_if_stale(model)
                model = await self._reload_authoritative(model)
                if model.status == APPROVAL_STATUS_PENDING:
                    model = await self._create_bind_and_observe_remote(
                        model,
                        arguments,
                        estimated_credits,
                    )
                check = self._check(model)
            else:
                check = await self._refresh(model)
            return await self._finalize(
                model,
                check,
                consume_immediately=consume_immediately,
            )

        # The database clock defines both ends of the observation window.
        # Worker skew must not extend or prematurely close human authority.
        now = await self._database_utc_now()
        expires_at = now + timedelta(seconds=self._timeout_seconds())
        model = HumanApprovalModel(
            approval_id=f"appr-{uuid.uuid4().hex[:16]}",
            wallet_id=wallet_id,
            permit_id=permit_id,
            tool=tool_name,
            idempotency_key=idempotency_key,
            status=APPROVAL_STATUS_PENDING,
            simulated=simulated,
            request_hash=req_hash,
            requested_at=now,
            expires_at=expires_at,
        )

        if simulated:
            # Local/dev only (production-like was rejected above): approve
            # instantly in the insert itself, clearly marked, so a crash cannot
            # strand a synthetic pending row. ``now`` came from the database.
            model.status = APPROVAL_STATUS_APPROVED
            model.decided_by = "simulation"
            model.reason = "simulated_auto_approval"
            model.decided_at = now
            model = await self._persist_new(model)
            self._reauthorize(model, req_hash=req_hash, production_like=production_like)
            return await self._finalize(
                model,
                self._check(model),
                consume_immediately=consume_immediately,
            )

        # Persist the request identity and its database-authored deadline
        # before contacting Sentinel. A provider commit followed by worker
        # death must not let a retry mint a fresh observation window.
        model = await self._persist_new(model)
        # The winner of a concurrent race may carry different binding/simulated
        # state; re-validate against the authoritative row before consuming.
        self._reauthorize(model, req_hash=req_hash, production_like=production_like)
        if model.status == APPROVAL_STATUS_PENDING and not model.sentinel_action_id:
            model = await self._create_bind_and_observe_remote(
                model,
                arguments,
                estimated_credits,
            )
        return await self._finalize(
            model,
            self._check(model),
            consume_immediately=consume_immediately,
        )

    @staticmethod
    def _reauthorize(
        model: HumanApprovalModel, *, req_hash: str, production_like: bool
    ) -> None:
        """Re-check a (possibly reloaded) approval against this invoke + env.

        Both guards matter on the reload path, which the fresh-create guards
        never see: a dev-minted *simulated* approval must not authorize an
        invoke once the environment is production-like, and an approval must
        bind to the exact ``(tool, arguments, estimated_credits)`` request the
        human reviewed.
        """
        if model.simulated and production_like:
            raise HumanApprovalError("human_approval_not_configured")
        if model.request_hash != req_hash:
            if model.request_hash is None:
                # Pre-024 approvals have no bound hash; they fail closed here.
                # Distinct log so a migration-era denial isn't mistaken for a
                # real argument-swap attempt (drain pending approvals before
                # deploying 024 to avoid this).
                logger.warning(
                    "human_approval_unbound_pre_migration approval_id=%s",
                    model.approval_id,
                )
            raise HumanApprovalError(APPROVAL_REASON_MISMATCH)

    async def _finalize(
        self,
        model: HumanApprovalModel,
        check: ApprovalCheck,
        *,
        consume_immediately: bool,
    ) -> ApprovalCheck:
        """Consume an approved decision so it authorizes exactly one invoke."""
        if check.status != APPROVAL_STATUS_APPROVED or not consume_immediately:
            return check
        if await self._consume(model.approval_id):
            return check  # this invoke holds the single-use authorization
        # Lost the single-use race: report why so the router denies correctly.
        latest = await self._load(
            wallet_id=model.wallet_id,
            permit_id=model.permit_id,
            tool_name=model.tool,
            idempotency_key=model.idempotency_key,
        )
        if latest is None or latest.status == APPROVAL_STATUS_APPROVED:
            # An approved-but-unconsumable row is unexpected after the
            # single-use compare-and-swap. Fail closed rather than returning
            # an authorization this caller did not consume.
            status: str = APPROVAL_STATUS_EXPIRED
        else:
            status = latest.status
        return ApprovalCheck(
            status=status,
            approval_id=model.approval_id,
            sentinel_action_id=model.sentinel_action_id,
            simulated=model.simulated,
            decided_by=model.decided_by,
            reason=model.reason,
            expires_at=model.expires_at,
        )

    async def _persist_new(self, model: HumanApprovalModel) -> HumanApprovalModel:
        """Insert a new approval; on a concurrent-insert race return the winner.

        The winner is the authoritative row — with a deterministic Sentinel
        Idempotency-Key both racers created (or replayed) the same Sentinel
        approval, so falling back to the persisted row is consistent.
        """
        try:
            await self._persist(model)
            return model
        except IntegrityError:
            existing = await self._load(
                wallet_id=model.wallet_id,
                permit_id=model.permit_id,
                tool_name=model.tool,
                idempotency_key=model.idempotency_key,
            )
            if existing is None:  # pragma: no cover - repair path
                raise
            return existing

    async def _reload_authoritative(
        self,
        model: HumanApprovalModel,
    ) -> HumanApprovalModel:
        latest = await self._load(
            wallet_id=model.wallet_id,
            permit_id=model.permit_id,
            tool_name=model.tool,
            idempotency_key=model.idempotency_key,
        )
        if latest is None:  # pragma: no cover - deleted-row repair path
            raise HumanApprovalUnavailableError()
        return latest

    async def _observe_persisted_decision(
        self,
        model: HumanApprovalModel,
        payload: dict[str, Any],
    ) -> HumanApprovalModel:
        """Apply a provider decision only through the durable guarded CAS."""
        if model.status != APPROVAL_STATUS_PENDING:
            return model
        self._apply_decision(model, payload)
        if model.status == APPROVAL_STATUS_PENDING:
            return model
        await self._persist_decision(model)
        return await self._reload_authoritative(model)

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
                idempotency_key=sentinel_idempotency_key(
                    model.wallet_id,
                    model.permit_id,
                    model.tool,
                    model.idempotency_key,
                    model.request_hash or "",
                ),
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

    async def _persist_sentinel_action(
        self,
        model: HumanApprovalModel,
        action_id: str,
    ) -> HumanApprovalModel:
        """Bind the deterministic provider action without rewriting state."""
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(HumanApprovalModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.approval_id == model.approval_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        HumanApprovalModel.status == APPROVAL_STATUS_PENDING,
                    ),
                    cast(
                        ColumnElement[bool],
                        cast(Any, HumanApprovalModel.sentinel_action_id).is_(None),
                    ),
                )
                .values(sentinel_action_id=action_id)
            )
            await session.commit()
        latest = await self._reload_authoritative(model)
        if latest.sentinel_action_id != action_id:
            # The deterministic provider key must resolve to one action. A
            # mismatch is external evidence ambiguity, never authority.
            raise HumanApprovalUnavailableError()
        return latest

    async def _create_bind_and_observe_remote(
        self,
        model: HumanApprovalModel,
        arguments: dict[str, Any],
        estimated_credits: Any,
    ) -> HumanApprovalModel:
        """Create/replay Sentinel action, bind it, then observe its decision."""
        remote = await self._create_remote(model, arguments, estimated_credits)
        action_id = model.sentinel_action_id
        if not action_id:  # guarded by _create_remote; keeps this fail closed
            raise HumanApprovalUnavailableError()
        model = await self._persist_sentinel_action(model, action_id)
        decision_payload = remote
        remote_status = remote.get("status") or remote.get("decision") or ""
        wait_seconds = float(get_settings().SENTINEL_WAIT_SECONDS or 0)
        if (
            remote_status not in {APPROVAL_STATUS_APPROVED, APPROVAL_STATUS_REJECTED}
            and wait_seconds > 0
        ):
            try:
                decision_payload = await self._sentinel().wait_approval(
                    action_id,
                    wait_seconds,
                )
            except httpx.HTTPError as exc:
                # The action binding is durable; a failed wait is retryable.
                logger.warning("sentinel_wait_failed: %s", exc)
        return await self._observe_persisted_decision(model, decision_payload)

    async def _refresh(self, model: HumanApprovalModel) -> ApprovalCheck:
        """Re-evaluate a stored approval using database-authoritative time."""
        if model.status != APPROVAL_STATUS_PENDING:
            return self._check(model)

        # Ask the database to expire first on every pending observation. A
        # worker-local precheck would let a slow clock poll and persist a late
        # approval as if it were timely.
        await self._expire_if_stale(model)
        model = await self._reload_authoritative(model)
        if model.status != APPROVAL_STATUS_PENDING:
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
            # Record the decision with a conditional update guarded on
            # status='pending'. A blind write would rewrite every column and
            # could revive a row a concurrent retry already advanced to
            # 'consumed' back to 'approved', letting its consume win a second
            # time (one human approval, two charges). The atomic _consume
            # reads the authoritative DB state regardless of this no-op.
            await self._persist_decision(model)
            model = await self._reload_authoritative(model)
        return self._check(model)

    async def _persist_decision(self, model: HumanApprovalModel) -> bool:
        """Persist a pending→approved/rejected decision without clobbering a
        row a concurrent request already advanced (approved/consumed)."""
        if model.status not in {
            APPROVAL_STATUS_APPROVED,
            APPROVAL_STATUS_REJECTED,
        }:
            return False
        factory = get_session_factory()
        async with factory() as session:
            database_now = self._database_utc_now_expression(session)
            predicates: list[ColumnElement[bool]] = [
                cast(
                    ColumnElement[bool],
                    HumanApprovalModel.approval_id == model.approval_id,
                ),
                cast(
                    ColumnElement[bool],
                    HumanApprovalModel.status == APPROVAL_STATUS_PENDING,
                ),
            ]
            if model.status == APPROVAL_STATUS_APPROVED:
                predicates.extend(
                    [
                        cast(
                            ColumnElement[bool],
                            HumanApprovalModel.requested_at <= database_now,
                        ),
                        cast(
                            ColumnElement[bool],
                            database_now < HumanApprovalModel.expires_at,
                        ),
                    ]
                )
            result = await session.execute(
                update(HumanApprovalModel)
                .where(*predicates)
                .values(
                    status=model.status,
                    decided_by=model.decided_by,
                    reason=model.reason,
                    decided_at=database_now,
                )
            )
            await session.commit()
            changed = bool(cast(Any, result).rowcount)
        if model.status == APPROVAL_STATUS_APPROVED and not changed:
            # If the approval lost specifically because the database deadline
            # elapsed, persist that terminal fact. This is also guarded against
            # clobbering a concurrent approval/consume winner.
            await self._expire_if_stale(model)
        return changed


_service: HumanApprovalService | None = None


def get_human_approval_service() -> HumanApprovalService:
    global _service
    if _service is None:
        _service = HumanApprovalService()
    return _service
