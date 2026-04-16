"""
Tests for B2A SDK.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from b2a_sdk import B2AClient, InsufficientFundsError, billable, monitored


class TestB2AClient:
    """Tests for the B2AClient class."""

    @pytest.fixture
    def client(self):
        return B2AClient(api_key="test-key", base_url="http://test")

    @pytest.mark.asyncio
    async def test_charge_success(self, client):
        """Test successful charge request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "action": "debit",
            "amount": -20.0,
            "balance_after": 4980.0,
        }

        with patch.object(client._client, "post", return_value=mock_response):
            result = await client.charge("wallet-123", "iot_bridge", units=10)

            assert result["action"] == "debit"
            assert result["amount"] == -20.0

    @pytest.mark.asyncio
    async def test_charge_insufficient_funds(self, client):
        """Test charge raises InsufficientFundsError on 402."""
        mock_response = MagicMock()
        mock_response.status_code = 402
        mock_response.json.return_value = {
            "detail": {
                "shortfall": "100.0",
            }
        }

        with patch.object(client._client, "post", return_value=mock_response):
            with pytest.raises(InsufficientFundsError) as exc_info:
                await client.charge("wallet-123", "iot_bridge", units=100)

            assert exc_info.value.wallet_id == "wallet-123"
            assert exc_info.value.shortfall == 100.0

    @pytest.mark.asyncio
    async def test_telemetry_non_blocking(self, client):
        """Test telemetry failures don't block execution."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("Network error")

        with patch.object(client._client, "post", return_value=mock_response):
            await client.telemetry(
                event_type="api_call",
                source="test_service",
                message="Test message",
            )

    @pytest.mark.asyncio
    async def test_create_sponsor_wallet(self, client):
        """Test sponsor wallet creation."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "wallet_id": "spn-123",
            "wallet_type": "sponsor",
            "balance": 50000.0,
        }

        with patch.object(client._client, "post", return_value=mock_response):
            result = await client.create_sponsor_wallet(
                sponsor_name="Test Corp",
                email="test@example.com",
                initial_credits=50000.0,
            )

            assert result["wallet_id"] == "spn-123"
            assert result["balance"] == 50000.0

    @pytest.mark.asyncio
    async def test_get_wallet(self, client):
        """Test getting wallet details."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "wallet_id": "agt-123",
            "balance": 5000.0,
            "status": "active",
        }

        with patch.object(client._client, "get", return_value=mock_response):
            result = await client.get_wallet("agt-123")
            assert result["wallet_id"] == "agt-123"

    @pytest.mark.asyncio
    async def test_get_balance(self, client):
        """Test getting wallet balance."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "wallet_id": "agt-123",
            "balance": 5000.0,
        }

        with patch.object(client._client, "get", return_value=mock_response):
            balance = await client.get_balance("agt-123")
            assert balance == 5000.0

    @pytest.mark.asyncio
    async def test_prepare_top_up(self, client):
        """Test fiat top-up preparation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_secret": "pi_xxx_secret",
            "payment_intent_id": "pi_xxx",
            "amount_credits": 50000,
            "amount_fiat": 50.0,
        }

        with patch.object(client._client, "post", return_value=mock_response):
            result = await client.prepare_top_up("wallet-123", 50.0)

            assert result["amount_credits"] == 50000
            assert result["client_secret"] == "pi_xxx_secret"


class TestDecorators:
    """Tests for the @monitored and @billable decorators."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=B2AClient)
        client.telemetry = AsyncMock()
        client.charge = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_monitored_decorator_success(self, mock_client):
        """Test @monitored fires telemetry on success."""
        @monitored(mock_client, service_name="test_service")
        async def my_function():
            return "success"

        result = await my_function()

        assert result == "success"
        mock_client.telemetry.assert_called_once()
        call_kwargs = mock_client.telemetry.call_args.kwargs
        assert call_kwargs["source"] == "test_service"
        assert call_kwargs["severity"] == "info"

    @pytest.mark.asyncio
    async def test_monitored_decorator_error(self, mock_client):
        """Test @monitored fires error telemetry on exception."""
        @monitored(mock_client, service_name="test_service")
        async def my_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await my_function()

        mock_client.telemetry.assert_called_once()
        call_kwargs = mock_client.telemetry.call_args.kwargs
        assert call_kwargs["event_type"] == "error"
        assert call_kwargs["severity"] == "high"

    @pytest.mark.asyncio
    async def test_billable_decorator_success(self, mock_client):
        """Test @billable charges before execution."""
        @billable(mock_client, wallet_id="wallet-123", service_category="iot_bridge", units=5.0)
        async def my_function():
            return "success"

        result = await my_function()

        assert result == "success"
        mock_client.charge.assert_called_once()
        call_kwargs = mock_client.charge.call_args.kwargs
        assert call_kwargs["wallet_id"] == "wallet-123"
        assert call_kwargs["service_category"] == "iot_bridge"
        assert call_kwargs["units"] == 5.0
        assert "my_function" in call_kwargs["request_path"]

    @pytest.mark.asyncio
    async def test_billable_decorator_insufficient_funds(self, mock_client):
        """Test @billable raises on insufficient funds."""
        mock_client.charge.side_effect = InsufficientFundsError(
            wallet_id="wallet-123",
            shortfall=100.0,
            top_up_url="http://test/top-up",
        )

        @billable(mock_client, wallet_id="wallet-123", service_category="iot_bridge", units=100.0)
        async def my_function():
            return "success"

        with pytest.raises(InsufficientFundsError):
            await my_function()


class TestInsufficientFundsError:
    """Tests for InsufficientFundsError."""

    def test_error_attributes(self):
        """Test error has correct attributes."""
        error = InsufficientFundsError(
            wallet_id="wallet-123",
            shortfall=100.0,
            top_up_url="http://test/top-up",
        )

        assert error.wallet_id == "wallet-123"
        assert error.shortfall == 100.0
        assert "wallet-123" in str(error)
        assert "100.0" in str(error)

    def test_error_unknown_shortfall(self):
        """Test error handles unknown shortfall."""
        error = InsufficientFundsError(
            wallet_id="wallet-123",
            shortfall="unknown",
            top_up_url="http://test/top-up",
        )

        assert error.shortfall is None
