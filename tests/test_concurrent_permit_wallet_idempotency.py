"""Concurrency guards for permit reserve, wallet debit, idempotency insert.

Adversarial tests over the three shared-row write paths: concurrent reserves
against one permit cap, concurrent debits against one wallet balance,
concurrent inserts under one idempotency key, plus the seams around them
(negative amounts, abandon racing complete, lock-shaped insert failures, the
governed daily cap). The core guarded-UPDATE paths hold under races on both
SQLite and PostgreSQL; the service-layer seams below each failed before its
fix and passes after.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, PermitModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.schemas.trust import PermitCreateRequest
from app.services.agent_money import get_agent_money
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.permits import PermitError, get_permit_service
from tests.conftest import interleaving_factory, requires_sqlite_row_lock_noop
from tests.test_trust_helpers import provision_agent_wallet

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


async def _permit_with_budget(client, *, max_credits: str = "10"):
    provisioned = await provision_agent_wallet(client)
    permit = await get_permit_service().create_permit(
        PermitCreateRequest(
            issuer_wallet_id=provisioned["agent_wallet_id"],
            subject_wallet_id=provisioned["agent_wallet_id"],
            subject_key_id=provisioned["key_id"],
            allowed_tools=["brk-tool"],
            scopes=["tool:brk-tool:invoke"],
            max_credits=Decimal(max_credits),
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).replace(
                tzinfo=None
            ),
        )
    )
    return provisioned, permit


async def _spent(permit_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit_id)
        assert model is not None
        return model.spent_credits


async def _set_balance_and_daily(
    wallet_id: str, balance: Decimal, daily_limit: Decimal | None = None
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            wallet.balance = balance
            wallet.daily_spent = Decimal("0")
            wallet.hourly_spent = Decimal("0")
            if daily_limit is not None:
                wallet.daily_limit = daily_limit
            session.add(wallet)


async def _balance(wallet_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.balance


async def _daily_spent(wallet_id: str) -> Decimal:
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        return wallet.daily_spent


# --------------------------------------------------------------------------
# Negative amounts at the permit service layer
# --------------------------------------------------------------------------


async def test_reserve_budget_refuses_negative_amount(client, clean_database):
    """A negative reserve must not shrink spent_credits (mint budget)."""
    _, permit = await _permit_with_budget(client)
    before = await _spent(permit.permit_id)
    with pytest.raises(PermitError, match="permit_invalid_amount"):
        await get_permit_service().reserve_budget(permit.permit_id, Decimal("-5"))
    assert await _spent(permit.permit_id) == before


async def test_release_budget_refuses_negative_amount(client, clean_database):
    """A negative release must not inflate spent_credits (burn budget)."""
    _, permit = await _permit_with_budget(client)
    await get_permit_service().reserve_budget(permit.permit_id, Decimal("4"))
    before = await _spent(permit.permit_id)
    assert before == Decimal("4")
    with pytest.raises(PermitError, match="permit_invalid_amount"):
        await get_permit_service().release_budget(permit.permit_id, Decimal("-5"))
    assert await _spent(permit.permit_id) == before


async def test_authorize_and_reserve_refuses_negative_estimate(client, clean_database):
    """A negative estimate must never authorize nor move spent_credits."""
    provisioned, permit = await _permit_with_budget(client)
    before = await _spent(permit.permit_id)
    with pytest.raises(PermitError, match="permit_invalid_amount"):
        await get_permit_service().authorize_and_reserve(
            permit_id=permit.permit_id,
            wallet_id=provisioned["agent_wallet_id"],
            tool_name="brk-tool",
            estimated_credits=Decimal("-5"),
            key_id=provisioned["key_id"],
        )
    assert await _spent(permit.permit_id) == before


async def test_zero_amounts_stay_harmless_noops(client, clean_database):
    """The guard rejects negatives only: zero reserves and releases still work."""
    provisioned, permit = await _permit_with_budget(client)
    await get_permit_service().reserve_budget(permit.permit_id, Decimal("0"))
    await get_permit_service().release_budget(permit.permit_id, Decimal("0"))
    assert await _spent(permit.permit_id) == Decimal("0")
    validation = await get_permit_service().authorize_and_reserve(
        permit_id=permit.permit_id,
        wallet_id=provisioned["agent_wallet_id"],
        tool_name="brk-tool",
        estimated_credits=Decimal("0"),
        key_id=provisioned["key_id"],
    )
    assert validation.allowed
    assert await _spent(permit.permit_id) == Decimal("0")


# --------------------------------------------------------------------------
# abandon() racing complete() on the same record (SQLite only)
# --------------------------------------------------------------------------


@requires_sqlite_row_lock_noop
async def test_abandon_does_not_delete_a_completed_record(
    client, clean_database, monkeypatch
):
    """A complete() that lands inside abandon()'s read window must survive.

    abandon() reads the record, checks it carries no response, then deletes.
    On SQLite the row lock is a no-op, so a concurrent complete() can commit
    a response between that read and the delete, and abandon() erases the
    replay protection for a charge that already moved money.
    """
    import app.services.idempotency as idem_module

    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    idem = get_idempotency_service()
    begun = await idem.begin_with_record(
        wallet_id=wallet_id,
        endpoint="/probe/abandon",
        idempotency_key="brk-abandon-key",
        request_payload={"op": "a"},
    )
    assert begun.replay is None

    real_factory = get_session_factory()
    state: dict = {}

    async def _concurrent_complete() -> None:
        await idem.complete(
            wallet_id=wallet_id,
            endpoint="/probe/abandon",
            idempotency_key="brk-abandon-key",
            response_reference="receipt-1",
            response_json={"ok": True},
        )

    hooked = interleaving_factory(real_factory, _concurrent_complete, state, fire_on=1)

    # interleaving_factory returns a double-called provider; the idempotency
    # service calls get_session_factory() once and the result once, so hand
    # it the inner provider directly.
    monkeypatch.setattr(idem_module, "get_session_factory", lambda: hooked())

    abandoned = await get_idempotency_service().abandon(
        wallet_id=wallet_id,
        endpoint="/probe/abandon",
        idempotency_key="brk-abandon-key",
    )
    assert state.get("fired"), "the interleave never ran, the test proved nothing"
    assert abandoned is False, "abandon deleted a record carrying a response"
    factory = real_factory()
    async with factory as session:
        row = (
            await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.wallet_id == wallet_id,
                    IdempotencyRecordModel.endpoint == "/probe/abandon",
                    IdempotencyRecordModel.idempotency_key == "brk-abandon-key",
                )
            )
        ).scalar_one_or_none()
    assert row is not None, "completed record is gone"
    assert row.response_reference == "receipt-1"


# --------------------------------------------------------------------------
# Idempotency insert hitting a non-"database is locked" lock error
# --------------------------------------------------------------------------


async def test_begin_replays_winner_on_table_locked_error(
    client, clean_database, monkeypatch
):
    """begin_with_record must not leak a raw OperationalError on lock races.

    The insert path translates IntegrityError (lost insert race) and
    OperationalError("database is locked"), but any other lock-shaped driver
    error, e.g. "database table is locked", escapes as a raw 500 while a
    winner row may already be durable.
    """
    import app.services.idempotency as idem_module

    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    real_factory = get_session_factory()

    from app.services.signing_keys import sha256_hex

    async def _install_winner() -> None:
        winner_factory = real_factory()
        async with winner_factory as session:
            async with session.begin():
                from app.db.models import IdempotencyRecordModel as M

                session.add(
                    M(
                        record_id="idm-winner",
                        wallet_id=wallet_id,
                        endpoint="/probe/lock",
                        idempotency_key="brk-lock-key",
                        request_hash=sha256_hex({"op": "x"}),
                        operation_kind="probe",
                        response_reference="receipt-w",
                        response_json='{"ok": true}',
                        status_code=200,
                    )
                )

    fired: dict = {}

    class _Session:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def commit(self):
            if not fired.get("done"):
                fired["done"] = True
                await _install_winner()
                raise OperationalError(
                    "INSERT INTO idempotency_records",
                    {},
                    Exception("database table is locked"),
                )
            return await self._inner.commit()

    class _CM:
        def __init__(self, cm):
            self._cm = cm

        async def __aenter__(self):
            return _Session(await self._cm.__aenter__())

        async def __aexit__(self, *exc):
            return await self._cm.__aexit__(*exc)

    single_call_provider = lambda: _CM(real_factory())  # noqa: E731
    monkeypatch.setattr(
        idem_module, "get_session_factory", lambda: single_call_provider
    )
    begun = await get_idempotency_service().begin_with_record(
        wallet_id=wallet_id,
        endpoint="/probe/lock",
        idempotency_key="brk-lock-key",
        request_payload={"op": "x"},
    )
    assert fired.get("done"), "the injection never ran"
    assert begun.record_id == "idm-winner"
    assert begun.replay is not None


# --------------------------------------------------------------------------
# Genuine concurrent races (holds expected, proves guards work)
# --------------------------------------------------------------------------


async def test_concurrent_reserves_cannot_overspend(client, clean_database):
    """Six concurrent 3-credit reserves against a 10-credit cap."""
    provisioned, permit = await _permit_with_budget(client, max_credits="10")

    async def _one():
        try:
            return await get_permit_service().authorize_and_reserve(
                permit_id=permit.permit_id,
                wallet_id=provisioned["agent_wallet_id"],
                tool_name="brk-tool",
                estimated_credits=Decimal("3"),
                key_id=provisioned["key_id"],
            )
        except PermitError as exc:
            return exc

    results = await asyncio.gather(*[_one() for _ in range(6)])
    allowed = sum(1 for r in results if not isinstance(r, Exception) and r.allowed)
    for r in results:
        if isinstance(r, Exception):
            assert isinstance(r, PermitError), f"unexpected escape: {r!r}"
        elif not r.allowed:
            assert r.reason in {
                "permit_budget_exceeded",
                "permit_write_contended",
            }, r.reason
    spent = await _spent(permit.permit_id)
    assert spent == allowed * Decimal("3")
    assert spent <= Decimal("10")


async def test_concurrent_debits_cannot_overdraw(client, clean_database):
    """Eight concurrent 30-credit standalone charges against balance 100."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    await _set_balance_and_daily(wallet_id, Decimal("100"))

    money = get_agent_money()

    async def _one(i: int):
        try:
            return await money.charge(
                wallet_id=wallet_id,
                service_category=ServiceCategory.TELEMETRY_PM,
                units=Decimal("30"),
                request_path=f"/probe-{i}",
            )
        except OperationalError as exc:
            return exc

    results = await asyncio.gather(*[_one(i) for i in range(8)])
    from app.schemas.billing import InsufficientFundsResponse, LedgerEntry

    debited = Decimal("0")
    for r in results:
        if isinstance(r, LedgerEntry):
            debited += Decimal(str(-r.amount))
        elif isinstance(r, OperationalError):
            pytest.fail(f"contention escaped as raw OperationalError: {r}")
        else:
            assert isinstance(r, InsufficientFundsResponse), f"unexpected: {r!r}"
    balance = await _balance(wallet_id)
    assert balance >= Decimal("0")
    assert balance == Decimal("100") - debited


async def test_concurrent_idem_inserts_have_a_single_winner(client, clean_database):
    """Eight concurrent identical begins: one row, no raw IntegrityError."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    idem = get_idempotency_service()

    async def _one():
        try:
            return await idem.begin_with_record(
                wallet_id=wallet_id,
                endpoint="/probe/race",
                idempotency_key="brk-race-key",
                request_payload={"op": "same"},
            )
        except (IdempotencyInProgressError, IdempotencyConflictError) as exc:
            return exc
        except IntegrityError as exc:
            return exc

    results = await asyncio.gather(*[_one() for _ in range(8)])
    begun = [r for r in results if not isinstance(r, Exception)]
    assert begun, "no begin won the race at all"
    assert {b.record_id for b in begun} == {begun[0].record_id}
    for r in results:
        if isinstance(r, Exception):
            assert isinstance(
                r, (IdempotencyInProgressError, IdempotencyConflictError)
            ), f"raw error escaped: {r!r}"
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.wallet_id == wallet_id,
                        IdempotencyRecordModel.endpoint == "/probe/race",
                        IdempotencyRecordModel.idempotency_key == "brk-race-key",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


# --------------------------------------------------------------------------
# Governed daily-cap race (the hard shared-counter check)
# --------------------------------------------------------------------------


async def test_governed_daily_cap_holds_under_concurrency(client, clean_database):
    """Two concurrent 60-credit governed charges against daily_limit 100.

    Velocity increments are transactional on the governed path, so each
    charge's cap check can run against a daily total that does not yet
    include the other's increment. The guarded debit UPDATE is the only
    statement that can still refuse, and it carries no daily predicate.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    await _set_balance_and_daily(wallet_id, Decimal("1000"), Decimal("100"))

    idem = get_idempotency_service()
    money = get_agent_money()
    keys = []
    for i in range(2):
        begun = await idem.begin_with_record(
            wallet_id=wallet_id,
            endpoint="/probe/daily",
            idempotency_key=f"brk-daily-{i}",
            request_payload={"op": i},
            operation_kind="probe",
        )
        keys.append(begun.record_id)

    async def _one(key: str, i: int):
        return await money.charge(
            wallet_id=wallet_id,
            service_category=ServiceCategory.TELEMETRY_PM,
            units=Decimal("60"),
            request_path=f"/probe-daily-{i}",
            operation_key=key,
        )

    results = await asyncio.gather(*[_one(k, i) for i, k in enumerate(keys)])
    from app.schemas.billing import InsufficientFundsResponse, LedgerEntry

    debited = Decimal("0")
    denied = 0
    for r in results:
        if isinstance(r, LedgerEntry):
            debited += Decimal("60")
        else:
            assert isinstance(r, InsufficientFundsResponse), f"unexpected: {r!r}"
            denied += 1
    assert debited <= Decimal("100"), (
        f"daily cap 100 exceeded: debited {debited}, denied {denied}"
    )
    assert denied >= 1, "both charges succeeded against a cap only one fits"
