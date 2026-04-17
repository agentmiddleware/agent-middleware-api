"""
Tests for multi-tenant hardening validations.
"""

import pytest

from fastapi import HTTPException

from app.core.tenant_validation import (
    TenantIsolationError,
    validate_tenant_access,
    validate_wallet_access,
    validate_agent_access,
    validate_session_access,
    validate_service_access,
    assert_no_tenant_leakage,
    require_tenant_isolation,
)


class TestTenantIsolation:
    """Test tenant isolation validations."""

    def test_same_tenant_access_allowed(self):
        """Access to own resources should be allowed."""
        validate_tenant_access(
            resource_owner_key="key-123",
            requester_api_key="key-123",
            resource_type="wallet",
            resource_id="wallet-001",
        )

    def test_cross_tenant_access_denied(self):
        """Access to other tenant's resources should be denied."""
        with pytest.raises(TenantIsolationError) as exc_info:
            validate_tenant_access(
                resource_owner_key="key-123",
                requester_api_key="key-456",
                resource_type="wallet",
                resource_id="wallet-001",
            )

        assert "wallet" in str(exc_info.value.detail).lower()
        assert "wallet-001" in str(exc_info.value.detail)
        assert "another tenant" in str(exc_info.value.detail).lower()

    def test_wallet_access_same_tenant(self):
        """Same tenant wallet access allowed."""
        validate_wallet_access(
            wallet_id="wallet-001",
            wallet_owner_key="owner-key",
            requester_api_key="owner-key",
        )

    def test_wallet_access_cross_tenant(self):
        """Cross-tenant wallet access denied."""
        with pytest.raises(TenantIsolationError):
            validate_wallet_access(
                wallet_id="wallet-001",
                wallet_owner_key="owner-key",
                requester_api_key="other-key",
            )

    def test_agent_access_same_tenant(self):
        """Same tenant agent access allowed."""
        validate_agent_access(
            agent_id="agent-001",
            agent_owner_key="owner-key",
            requester_api_key="owner-key",
        )

    def test_agent_access_cross_tenant(self):
        """Cross-tenant agent access denied."""
        with pytest.raises(TenantIsolationError):
            validate_agent_access(
                agent_id="agent-001",
                agent_owner_key="owner-key",
                requester_api_key="other-key",
            )

    def test_session_access_same_tenant(self):
        """Same tenant session access allowed."""
        validate_session_access(
            session_id="session-001",
            session_owner_key="owner-key",
            requester_api_key="owner-key",
        )

    def test_session_access_cross_tenant(self):
        """Cross-tenant session access denied."""
        with pytest.raises(TenantIsolationError):
            validate_session_access(
                session_id="session-001",
                session_owner_key="owner-key",
                requester_api_key="other-key",
            )

    def test_service_access_same_tenant(self):
        """Same tenant service access allowed."""
        validate_service_access(
            service_id="service-001",
            service_owner_key="owner-key",
            requester_api_key="owner-key",
        )

    def test_service_access_cross_tenant(self):
        """Cross-tenant service access denied."""
        with pytest.raises(TenantIsolationError):
            validate_service_access(
                service_id="service-001",
                service_owner_key="owner-key",
                requester_api_key="other-key",
            )


class TestTenantLeakageDetection:
    """Test detection of cross-tenant data leakage."""

    def test_no_leakage_clean_data(self):
        """Clean data should pass."""
        data = {
            "wallet_id": "wallet-001",
            "balance": 1000,
            "currency": "credits",
        }
        assert_no_tenant_leakage(data, requester_api_key="key-123")

    def test_leakage_detected_owner_key(self):
        """Should detect leaked owner_key."""
        data = {
            "wallet_id": "wallet-001",
            "owner_key": "other-tenant-key",
            "balance": 1000,
        }
        with pytest.raises(TenantIsolationError) as exc_info:
            assert_no_tenant_leakage(data, requester_api_key="key-123")

        assert "leakage" in str(exc_info.value.detail).lower()
        assert "owner_key" in str(exc_info.value.detail)

    def test_leakage_detected_api_key(self):
        """Should detect leaked api_key."""
        data = {
            "service_id": "service-001",
            "api_key": "other-tenant-key",
        }
        with pytest.raises(TenantIsolationError):
            assert_no_tenant_leakage(data, requester_api_key="key-123")

    def test_leakage_detected_tenant_id(self):
        """Should detect leaked tenant_id."""
        data = {
            "resource_id": "resource-001",
            "tenant_id": "other-tenant",
        }
        with pytest.raises(TenantIsolationError):
            assert_no_tenant_leakage(data, requester_api_key="key-123")

    def test_own_data_not_leakage(self):
        """Own tenant's data should not trigger leakage."""
        data = {
            "wallet_id": "wallet-001",
            "owner_key": "key-123",
            "balance": 1000,
        }
        assert_no_tenant_leakage(data, requester_api_key="key-123")


class TestRequireTenantIsolation:
    """Test tenant isolation requirement checks."""

    def test_valid_api_key_passes(self):
        """Valid API key should pass isolation check."""
        result = require_tenant_isolation(requester_api_key="valid-key-123")
        assert result is True

    def test_empty_api_key_fails(self):
        """Empty API key should fail."""
        with pytest.raises(TenantIsolationError):
            require_tenant_isolation(requester_api_key="")

    def test_none_api_key_fails(self):
        """None API key should fail."""
        with pytest.raises(TenantIsolationError):
            require_tenant_isolation(requester_api_key=None)
