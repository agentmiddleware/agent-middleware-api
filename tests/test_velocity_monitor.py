"""
Tests for Spend Velocity Monitoring.
Validates velocity tracking, anomaly detection, and auto-freeze.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app.services.velocity_monitor import (
    VelocityMonitor,
    VelocityCheckResult,
    WalletFrozenError,
)


class TestVelocityCheckResult:
    """Tests for VelocityCheckResult."""

    def test_allowed_result(self):
        result = VelocityCheckResult(
            allowed=True,
            reason="Within velocity limits",
        )
        assert result.allowed is True
        assert result.alert_triggered is False
        assert result.should_freeze is False

    def test_alert_result(self):
        result = VelocityCheckResult(
            allowed=True,
            reason="Hourly spend velocity exceeded",
            alert_triggered=True,
            exceeded_limit="hourly",
            current_spend=1500.0,
            limit=1000.0,
        )
        assert result.allowed is True
        assert result.alert_triggered is True
        assert result.exceeded_limit == "hourly"

    def test_freeze_result(self):
        result = VelocityCheckResult(
            allowed=False,
            reason="Wallet frozen due to anomalous spend velocity",
            alert_triggered=True,
            should_freeze=True,
        )
        assert result.allowed is False
        assert result.should_freeze is True


class TestVelocityMonitorReset:
    """Tests for hourly/daily counter reset logic."""

    def test_reset_hourly_after_1_hour(self):
        monitor = VelocityMonitor()
        wallet = MagicMock()
        wallet.hourly_reset_at = datetime.now(timezone.utc) - timedelta(hours=2)
        wallet.hourly_spent = Decimal("500")
        wallet.daily_reset_at = datetime.now(timezone.utc)
        wallet.daily_spent = Decimal("1000")

        now = datetime.now(timezone.utc)
        monitor._reset_if_needed(wallet, now)

        assert wallet.hourly_spent == Decimal("0")
        assert wallet.hourly_reset_at == now

    def test_reset_daily_after_midnight(self):
        monitor = VelocityMonitor()
        wallet = MagicMock()
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        wallet.hourly_reset_at = yesterday
        wallet.hourly_spent = Decimal("500")
        wallet.daily_reset_at = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        wallet.daily_spent = Decimal("1000")

        now = datetime.now(timezone.utc)
        monitor._reset_if_needed(wallet, now)

        assert wallet.daily_spent == Decimal("0")
        assert wallet.daily_reset_at.date() == now.date()


class TestVelocityMonitorLimits:
    """Tests for velocity limit checking."""

    def test_within_limits(self):
        monitor = VelocityMonitor()
        wallet = MagicMock()
        wallet.wallet_id = "test-wallet"
        wallet.hourly_spent = Decimal("500")
        wallet.daily_spent = Decimal("5000")
        wallet.velocity_alerts_triggered = 0

        result = monitor._check_limits(
            wallet=wallet,
            hourly_limit=Decimal("1000"),
            daily_limit=Decimal("10000"),
            charge_amount=Decimal("100"),
        )

        assert result.allowed is True
        assert result.alert_triggered is False

    def test_hourly_limit_exceeded(self):
        monitor = VelocityMonitor()
        wallet = MagicMock()
        wallet.wallet_id = "test-wallet"
        wallet.hourly_spent = Decimal("1100")
        wallet.daily_spent = Decimal("5000")
        wallet.velocity_alerts_triggered = 0

        result = monitor._check_limits(
            wallet=wallet,
            hourly_limit=Decimal("1000"),
            daily_limit=Decimal("10000"),
            charge_amount=Decimal("100"),
        )

        assert result.allowed is True
        assert result.alert_triggered is True
        assert result.exceeded_limit == "hourly"
        assert result.should_freeze is False

    def test_freeze_after_threshold_exceeded(self):
        monitor = VelocityMonitor()
        wallet = MagicMock()
        wallet.wallet_id = "test-wallet"
        wallet.hourly_spent = Decimal("1100")
        wallet.daily_spent = Decimal("5000")
        wallet.velocity_alerts_triggered = 3

        result = monitor._check_limits(
            wallet=wallet,
            hourly_limit=Decimal("1000"),
            daily_limit=Decimal("10000"),
            charge_amount=Decimal("100"),
        )

        assert result.alert_triggered is True
        assert result.should_freeze is True


class TestVelocityMonitorIntegration:
    """Integration tests for velocity monitoring."""

    @pytest.mark.asyncio
    async def test_velocity_status_endpoint(self):
        """Test that velocity status endpoint returns correct data."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-API-Key": "test-key"}

            resp = await client.post(
                "/v1/billing/wallets/sponsor",
                json={"sponsor_name": "Test", "email": "t@t.com", "initial_credits": 10000},
                headers=headers,
            )
            wallet_id = resp.json()["wallet_id"]

            velocity_resp = await client.get(
                f"/v1/billing/wallets/{wallet_id}/velocity",
                headers=headers,
            )

            assert velocity_resp.status_code == 200
            data = velocity_resp.json()
            assert data["wallet_id"] == wallet_id
            assert "hourly_spent" in data
            assert "hourly_limit" in data
            assert "daily_spent" in data
            assert "daily_limit" in data
            assert "velocity_alerts" in data
