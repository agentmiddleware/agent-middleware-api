"""
Tests for Dry-Run Sandbox Integration
====================================

Tests for:
- Shadow ledger session creation and management
- Simulated charge tracking
- State accumulation (cumulative balance deduction)
- Session expiry and cleanup
- SDK simulate_session context manager
"""

import asyncio
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from app.services.shadow_ledger import (
    ShadowLedger,
    DryRunSession,
    SimulatedCharge,
    get_shadow_ledger,
)
from app.schemas.billing import ServiceCategory


class TestShadowLedger:
    """Test shadow ledger operations."""

    @pytest.fixture
    def ledger(self):
        return ShadowLedger()

    def test_create_session(self, ledger):
        """Creating a session returns a DryRunSession with unique ID."""
        session = asyncio.get_event_loop().run_until_complete(
            ledger.create_session(
                wallet_id="test-wallet",
                real_balance=Decimal("1000"),
            )
        )

        assert session is not None
        assert session.wallet_id == "test-wallet"
        assert session.real_balance == Decimal("1000")
        assert session.session_id is not None
        assert len(session.simulated_charges) == 0
        assert session.virtual_balance == Decimal("1000")

    def test_session_tracks_cumulative_charges(self, ledger):
        """Simulated charges accumulate in the session."""
        loop = asyncio.get_event_loop()

        session = loop.run_until_complete(
            ledger.create_session(
                wallet_id="test-wallet",
                real_balance=Decimal("1000"),
            )
        )

        result1 = loop.run_until_complete(
            ledger.simulate_charge(
                session_id=session.session_id,
                service_category=ServiceCategory.CONTENT_FACTORY,
                units=10.0,
                description="First charge",
            )
        )

        assert result1.would_succeed is True
        assert result1.simulated_balance_after == 500.0

        result2 = loop.run_until_complete(
            ledger.simulate_charge(
                session_id=session.session_id,
                service_category=ServiceCategory.IOT_BRIDGE,
                units=5.0,
                description="Second charge",
            )
        )

        assert result2.would_succeed is True
        assert result2.simulated_balance_after == 490.0

        final_session = loop.run_until_complete(
            ledger.get_session(session.session_id)
        )

        assert len(final_session.simulated_charges) == 2
        assert final_session.virtual_balance == Decimal("490")
        assert final_session.total_simulated == Decimal("510")

    def test_session_returns_insufficient_funds_when_exceeding_balance(self, ledger):
        """Simulated charges return would_succeed=False when exceeding virtual balance."""
        loop = asyncio.get_event_loop()

        session = loop.run_until_complete(
            ledger.create_session(
                wallet_id="test-wallet",
                real_balance=Decimal("100"),
            )
        )

        result = loop.run_until_complete(
            ledger.simulate_charge(
                session_id=session.session_id,
                service_category=ServiceCategory.CONTENT_FACTORY,
                units=50.0,
                description="Large charge",
            )
        )

        assert result.would_succeed is False
        assert result.simulated_balance_after < 0
        assert result.reason == "insufficient_simulated_funds"

    def test_session_end_returns_summary(self, ledger):
        """Ending a session returns a complete summary."""
        loop = asyncio.get_event_loop()

        session = loop.run_until_complete(
            ledger.create_session(
                wallet_id="test-wallet",
                real_balance=Decimal("500"),
            )
        )

        loop.run_until_complete(
            ledger.simulate_charge(
                session_id=session.session_id,
                service_category=ServiceCategory.TELEMETRY_PM,
                units=100.0,
                description="Test charge",
            )
        )

        summary = loop.run_until_complete(
            ledger.end_session(session.session_id)
        )

        assert summary is not None
        assert summary.wallet_id == "test-wallet"
        assert summary.total_simulated_credits == Decimal("100")
        assert summary.charge_count == 1
        assert summary.virtual_balance_after == Decimal("400")

    def test_nonexistent_session_returns_none(self, ledger):
        """Getting a nonexistent session returns None."""
        result = asyncio.get_event_loop().run_until_complete(
            ledger.get_session("nonexistent-id")
        )
        assert result is None

    def test_nonexistent_session_end_returns_none(self, ledger):
        """Ending a nonexistent session returns None."""
        result = asyncio.get_event_loop().run_until_complete(
            ledger.end_session("nonexistent-id")
        )
        assert result is None

    def test_virtual_balance_calculation(self, ledger):
        """Virtual balance correctly reflects real balance minus charges."""
        loop = asyncio.get_event_loop()

        session = loop.run_until_complete(
            ledger.create_session(
                wallet_id="test-wallet",
                real_balance=Decimal("1000"),
            )
        )

        for i in range(5):
            loop.run_until_complete(
                ledger.simulate_charge(
                    session_id=session.session_id,
                    service_category=ServiceCategory.IOT_BRIDGE,
                    units=1.0,
                    description=f"Charge {i}",
                )
            )

        final_session = loop.run_until_complete(
            ledger.get_session(session.session_id)
        )

        assert final_session.virtual_balance == Decimal("990")
        assert final_session.total_simulated == Decimal("10")


class TestDryRunSession:
    """Test DryRunSession dataclass."""

    def test_session_initialization(self):
        """Session initializes with correct defaults."""
        session = DryRunSession(
            session_id="test-123",
            wallet_id="wallet-456",
            real_balance=Decimal("1000"),
        )

        assert session.session_id == "test-123"
        assert session.wallet_id == "wallet-456"
        assert session.real_balance == Decimal("1000")
        assert session.simulated_charges == []
        assert session.total_simulated == Decimal("0")
        assert session.virtual_balance == Decimal("1000")

    def test_add_charge(self):
        """Adding a charge updates total_simulated and virtual_balance."""
        session = DryRunSession(
            session_id="test-123",
            wallet_id="wallet-456",
            real_balance=Decimal("1000"),
        )

        charge = SimulatedCharge(
            charge_id="ch-1",
            service_category="content_factory",
            units=10.0,
            credits=Decimal("500"),
            description="Test charge",
            timestamp=datetime.now(timezone.utc),
        )

        session.add_charge(charge)

        assert len(session.simulated_charges) == 1
        assert session.total_simulated == Decimal("500")
        assert session.virtual_balance == Decimal("500")

    def test_multiple_charges_accumulate(self):
        """Multiple charges accumulate correctly."""
        session = DryRunSession(
            session_id="test-123",
            wallet_id="wallet-456",
            real_balance=Decimal("1000"),
        )

        for i in range(3):
            session.add_charge(SimulatedCharge(
                charge_id=f"ch-{i}",
                service_category="content_factory",
                units=10.0,
                credits=Decimal("100"),
                description=f"Charge {i}",
                timestamp=datetime.now(timezone.utc),
            ))

        assert session.total_simulated == Decimal("300")
        assert session.virtual_balance == Decimal("700")


class TestGlobalSingleton:
    """Test global singleton getter."""

    def test_get_shadow_ledger(self):
        """get_shadow_ledger returns a ShadowLedger instance."""
        ledger = get_shadow_ledger()
        assert ledger is not None
        assert isinstance(ledger, ShadowLedger)


class TestBillingRouterDryRun:
    """Test dry-run endpoints in billing router."""

    @pytest.fixture
    async def client(self):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.anyio
    async def test_create_dry_run_session(self, client):
        """POST /v1/billing/dry-run/session creates a session."""
        wallet_resp = await client.post(
            "/v1/billing/wallets/sponsor",
            json={"sponsor_name": "Test Sponsor", "email": "test@example.com"},
            headers={"X-API-Key": "test-key"},
        )
        wallet_id = wallet_resp.json()["wallet_id"]

        response = await client.post(
            "/v1/billing/dry-run/session",
            json={"wallet_id": wallet_id},
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert data["wallet_id"] == wallet_id
        assert data["real_balance"] == 0.0
        assert data["virtual_balance"] == 0.0

    @pytest.mark.anyio
    async def test_simulate_charge(self, client):
        """POST /v1/billing/dry-run/charge simulates a charge."""
        wallet_resp = await client.post(
            "/v1/billing/wallets/sponsor",
            json={"sponsor_name": "Test Sponsor", "email": "test@example.com", "initial_credits": 10000},
            headers={"X-API-Key": "test-key"},
        )
        wallet_id = wallet_resp.json()["wallet_id"]

        response = await client.post(
            "/v1/billing/dry-run/charge",
            json={"wallet_id": wallet_id, "service": "content_factory", "units": 10.0},
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
        assert data["wallet_id"] == wallet_id
        assert data["service_category"] == "content_factory"
        assert data["units"] == 10.0
        assert data["credits_would_charge"] == 500.0

    @pytest.mark.anyio
    async def test_end_dry_run_session(self, client):
        """DELETE /v1/billing/dry-run/session/{id} ends session."""
        wallet_resp = await client.post(
            "/v1/billing/wallets/sponsor",
            json={"sponsor_name": "Test Sponsor", "email": "test@example.com", "initial_credits": 10000},
            headers={"X-API-Key": "test-key"},
        )
        wallet_id = wallet_resp.json()["wallet_id"]

        create_resp = await client.post(
            "/v1/billing/dry-run/session",
            json={"wallet_id": wallet_id},
            headers={"X-API-Key": "test-key"},
        )
        session_id = create_resp.json()["session_id"]

        await client.post(
            "/v1/billing/dry-run/charge",
            json={"wallet_id": wallet_id, "service": "iot_bridge", "units": 1.0, "dry_run_session_id": session_id},
            headers={"X-API-Key": "test-key"},
        )

        end_resp = await client.delete(
            f"/v1/billing/dry-run/session/{session_id}",
            headers={"X-API-Key": "test-key"},
        )

        assert end_resp.status_code == 200
        data = end_resp.json()
        assert data["session_id"] == session_id
        assert data["charge_count"] == 1
        assert data["total_simulated_credits"] == 2.0
