"""
Multi-Tenant Hardening Validations
==================================
Security validations for multi-tenant deployments.

These validations ensure tenant isolation by verifying that:
1. API keys can only access their own resources
2. Cross-tenant access attempts are rejected
3. Resource ownership is properly validated
"""

from typing import Any, Optional
from fastapi import HTTPException, status


class TenantIsolationError(HTTPException):
    """Raised when cross-tenant access is attempted."""

    def __init__(
        self, detail: str = "Access denied: resource belongs to another tenant"
    ):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "tenant_isolation_violation",
                "message": detail,
            },
        )


class TenantResource:
    """Represents a resource that belongs to a specific tenant."""

    def __init__(
        self, resource_id: str, owner_key: str, tenant_id: Optional[str] = None
    ):
        self.resource_id = resource_id
        self.owner_key = owner_key
        self.tenant_id = tenant_id or owner_key


def validate_tenant_access(
    resource_owner_key: str,
    requester_api_key: str,
    resource_type: str = "resource",
    resource_id: Optional[str] = None,
) -> None:
    """
    Validate that the requester has access to the resource.

    Args:
        resource_owner_key: The API key that owns the resource
        requester_api_key: The API key making the request
        resource_type: Type of resource (for error messages)
        resource_id: Optional ID of the resource (for error messages)

    Raises:
        TenantIsolationError: If cross-tenant access is detected
    """
    if resource_owner_key != requester_api_key:
        detail = f"Access denied: {resource_type}"
        if resource_id:
            detail += f" '{resource_id}'"
        detail += " belongs to another tenant"
        raise TenantIsolationError(detail)


def validate_wallet_access(
    wallet_id: str,
    wallet_owner_key: str,
    requester_api_key: str,
) -> None:
    """
    Validate that the requester can access the specified wallet.

    This ensures agents can't access wallets they don't own.
    """
    validate_tenant_access(
        resource_owner_key=wallet_owner_key,
        requester_api_key=requester_api_key,
        resource_type="wallet",
        resource_id=wallet_id,
    )


def validate_agent_access(
    agent_id: str,
    agent_owner_key: str,
    requester_api_key: str,
) -> None:
    """
    Validate that the requester can access the specified agent.
    """
    validate_tenant_access(
        resource_owner_key=agent_owner_key,
        requester_api_key=requester_api_key,
        resource_type="agent",
        resource_id=agent_id,
    )


def validate_session_access(
    session_id: str,
    session_owner_key: str,
    requester_api_key: str,
) -> None:
    """
    Validate that the requester can access the specified session.
    """
    validate_tenant_access(
        resource_owner_key=session_owner_key,
        requester_api_key=requester_api_key,
        resource_type="session",
        resource_id=session_id,
    )


def validate_service_access(
    service_id: str,
    service_owner_key: str,
    requester_api_key: str,
) -> None:
    """
    Validate that the requester can access the specified service.
    """
    validate_tenant_access(
        resource_owner_key=service_owner_key,
        requester_api_key=requester_api_key,
        resource_type="service",
        resource_id=service_id,
    )


def assert_no_tenant_leakage(data: dict[str, Any], requester_api_key: str) -> None:
    """
    Assert that a data dictionary doesn't contain cross-tenant information leaks.

    This checks for common patterns where tenant data might accidentally
    be exposed to other tenants.
    """
    suspicious_patterns = [
        ("owner_key", "another tenant's owner_key"),
        ("api_key", "another tenant's api_key"),
        ("tenant_id", "another tenant's tenant_id"),
    ]

    for key, description in suspicious_patterns:
        if key in data and data[key] != requester_api_key:
            raise TenantIsolationError(
                f"Data leakage detected: {description} found in response"
            )


class MultiTenantConfig:
    """Configuration for multi-tenant hardening."""

    def __init__(
        self,
        enforce_isolation: bool = True,
        allow_cross_tenant_audit: bool = False,
        log_violations: bool = True,
    ):
        self.enforce_isolation = enforce_isolation
        self.allow_cross_tenant_audit = allow_cross_tenant_audit
        self.log_violations = log_violations


DEFAULT_MULTITENANT_CONFIG = MultiTenantConfig()


def get_multitenant_config() -> MultiTenantConfig:
    """
    Get the multi-tenant configuration.

    In production, this would read from environment variables.
    """
    return DEFAULT_MULTITENANT_CONFIG


def require_tenant_isolation(requester_api_key: str) -> bool:
    """
    Check if tenant isolation is required for the given requester.

    Returns True if isolation should be enforced.
    """
    config = get_multitenant_config()

    if not config.enforce_isolation:
        return False

    if not requester_api_key or requester_api_key == "":
        raise TenantIsolationError("API key is required for tenant-isolated operations")

    return True
