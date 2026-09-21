"""Making an absorbed budget release visible instead of silent.

The MCP routers absorb a ``PermitWriteContendedError`` from the post-effects
budget release rather than propagating it, because the receipt is written
*after* that release and propagating would destroy the governance artifact for
a call that ran (pinned in ``test_permit_write_contention_surface``). The
absorb is correct; what it leaves behind is not free.

The permit keeps ``amount`` reserved against a call that was refunded, so
``spent_credits`` sits above what the receipts prove consumed.
``reconcile_budgets`` repairs exactly that drift -- but deliberately only for
permits that can no longer admit a charge, because downward-resetting a live
permit would open an over-spend window past ``max_credits``. A long-lived
permit therefore carries the inflation until it expires, and a later
legitimate call under it can be wrongly denied ``permit_budget_exceeded``.

These tests pin the two halves of making that observable without touching the
live-permit safety rule:

* the absorb records the stranded amount durably, and can never fail the call
  it is reporting on;
* ``reconcile_budgets`` *reports* live drift while still refusing to repair it.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.resilience import WRITE_CONFLICT_MAX_ATTEMPTS
from app.db.database import get_session_factory
from app.db.models import BillingAlertModel, PermitModel, ReceiptModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.permits import get_permit_service
from app.services.service_registry import get_service_registry
from tests.test_permit_write_contention_surface import (
    TOOL_COST,
    _lose_permit_writes,
    _rest_body,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def failing_tool():
    """A tool that runs, has its effect, then fails -- see the contention suite.

    Redeclared rather than imported: a fixture imported by name would register
    and unregister the same service id as the suite it came from, and the two
    would collide when both run in one session.
    """
    tool_name = "permit-drift-boom"
    runs = {"count": 0}

    def boom(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        raise RuntimeError("tool blew up")

    get_service_registry().register_local(
        service_id=tool_name,
        name="Permit drift boom",
        description="Post-effects budget drift visibility test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=boom,
        credits_per_unit=TOOL_COST,
        unit_name="call",
    )
    try:
        yield tool_name, runs
    finally:
        get_service_registry().unregister_local(tool_name)


async def _drift_alerts() -> list[BillingAlertModel]:
    factory = get_session_factory()
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(BillingAlertModel).where(
                        BillingAlertModel.alert_type == "permit_release_contended"
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.anyio
async def test_an_absorbed_release_records_the_credits_it_stranded(
    client: AsyncClient, clean_database: None, failing_tool
) -> None:
    """The absorb leaves a durable, per-permit trace, not just a log line.

    ``failures`` is bounded to the release ladder exactly, so the release
    exhausts and is absorbed while the alert write that follows it lands. That
    ordering is the test: the alert is written from inside the absorbing
    ``except``, after the release has definitively lost.
    """
    tool_name, runs = failing_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        idem_key="permit-drift-permit-1",
    )
    body = _rest_body(
        tool_name=tool_name,
        wallet_id=ctx["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="permit-drift-posteffects-1",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        _lose_permit_writes(
            monkeypatch, allow_first=1, failures=WRITE_CONFLICT_MAX_ATTEMPTS
        )
        resp = await client.post(
            f"/mcp/tools/{tool_name}/invoke", json=body, headers=ctx["agent_headers"]
        )

    # The premise: the tool ran, so this really is the post-effects release.
    assert runs["count"] == 1
    assert resp.json()["detail"]["receipt"]["outcome"] == "failed_refunded"

    alerts = await _drift_alerts()
    assert len(alerts) == 1, alerts
    alert = alerts[0]
    assert alert.wallet_id == ctx["agent_wallet_id"]
    assert alert.severity == "warning"
    # billing_alerts has no permit column, so the permit id travels in the
    # message the way the budget-threshold alerts already do.
    assert permit["permit_id"] in alert.message
    # The stranded reservation, which is what makes the drift actionable.
    assert alert.threshold_amount == Decimal(str(TOOL_COST))


@pytest.mark.anyio
async def test_a_lost_drift_alert_never_fails_the_call_it_reports_on(
    client: AsyncClient, clean_database: None, failing_tool
) -> None:
    """The alert write is best-effort, and must stay that way.

    It runs from inside the absorbing ``except``, *before* the receipt the
    absorb exists to protect has been written. An observability write that
    could propagate would re-create precisely the failure the absorb prevents
    -- so here every permit write loses, including the alert's own, and the
    call must still come back with its receipt.
    """
    tool_name, runs = failing_tool
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name=tool_name,
        idem_key="permit-drift-permit-2",
    )
    body = _rest_body(
        tool_name=tool_name,
        wallet_id=ctx["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="permit-drift-posteffects-2",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        # failures=None: nothing lands after the reserve, the alert included.
        _lose_permit_writes(monkeypatch, allow_first=1)
        resp = await client.post(
            f"/mcp/tools/{tool_name}/invoke", json=body, headers=ctx["agent_headers"]
        )

    assert runs["count"] == 1
    # The caller's real answer survived, receipt and all.
    detail = resp.json()["detail"]
    assert "tool blew up" in detail["error"], detail
    assert detail["receipt"]["outcome"] == "failed_refunded", detail

    factory = get_session_factory()
    async with factory() as session:
        receipts = (await session.execute(select(ReceiptModel))).scalars().all()
    assert len(receipts) == 1

    # The alert is what was sacrificed, and losing it costs only visibility --
    # reconcile_budgets still reports the drift from the permit row itself.
    assert await _drift_alerts() == []


async def _make_idle(permit_id: str, *, spent: Decimal) -> None:
    """Age a permit past the idle window with ``spent`` reserved.

    Active and unexpired throughout: this is the permit ``reconcile_budgets``
    must never repair, which is exactly why its drift needs reporting.
    """
    from datetime import datetime, timedelta, timezone

    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit_id)
        model.spent_credits = spent
        model.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.add(model)
        await session.commit()


def _drift_records(caplog) -> list[Any]:
    return [r for r in caplog.records if r.message == "permit_budget_live_drift"]


@pytest.mark.anyio
async def test_reconcile_reports_live_drift_but_still_refuses_to_repair_it(
    client: AsyncClient, clean_database: None, caplog
) -> None:
    """The whole point: visible before expiry, still never downward-reset.

    ``test_reconcile_budgets_never_resets_a_live_active_permit`` pins the
    safety half of this and must keep passing unchanged -- a live permit can
    still admit a charge, so resetting its reservation would let a concurrent
    request over-spend past ``max_credits``. What changes is only that the
    drift stops being invisible while it waits for expiry.
    """
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name="trust-echo",
        idem_key="permit-drift-permit-3",
    )
    # Nine credits reserved against zero receipts: pure drift.
    await _make_idle(permit["permit_id"], spent=Decimal("9"))

    caplog.set_level(logging.WARNING, logger="app.services.permits")
    corrected = await get_permit_service().reconcile_budgets(idle_seconds=900)

    # Unrepaired, exactly as before.
    assert corrected == 0
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit["permit_id"])
        assert model.spent_credits == Decimal("9")

    # But no longer silent.
    records = _drift_records(caplog)
    assert len(records) == 1, [r.message for r in caplog.records]
    assert records[0].permit_ids == [permit["permit_id"]]
    assert records[0].permits == 1
    # Compared as a Decimal, not a string: the column carries 8 decimal
    # places and pinning "9.00000000" would pin storage precision.
    assert Decimal(records[0].total_drift) == Decimal("9")


@pytest.mark.anyio
async def test_a_live_permit_whose_receipts_match_is_not_reported(
    client: AsyncClient, clean_database: None, caplog
) -> None:
    """The report has to stay quiet on healthy permits or it is unreadable.

    The permit is aged the same way as the drift case, so it is genuinely
    examined by the scan rather than skipped for being too recent -- without
    that, this test would pass while reporting nothing for the wrong reason.
    """
    ctx = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=ctx["agent_wallet_id"],
        key_id=ctx["key_id"],
        tool_name="trust-echo",
        idem_key="permit-drift-permit-4",
    )
    # Idle and scanned, but nothing reserved and no receipts -> no drift.
    await _make_idle(permit["permit_id"], spent=Decimal("0"))

    caplog.set_level(logging.WARNING, logger="app.services.permits")
    assert await get_permit_service().reconcile_budgets(idle_seconds=900) == 0

    assert _drift_records(caplog) == []
