"""The app.trust facade must re-export the canonical implementations.

If these identities ever drift, the product-core boundary has silently forked
from the underlying services — which is exactly what the facade exists to
prevent.
"""

from __future__ import annotations

import app.policy.decisions as decisions
import app.services.agent_money as agent_money
import app.services.audit_chain as audit_chain
import app.services.audit_log as audit_log
import app.services.governance as governance
import app.services.idempotency as idempotency
import app.services.permits as permits
import app.services.policies as policies
import app.services.receipts as receipts
import app.services.signing_keys as signing_keys
import app.trust as trust


def test_permits_facade_matches_service():
    assert trust.PermitService is permits.PermitService
    assert trust.get_permit_service is permits.get_permit_service
    assert trust.PermitError is permits.PermitError
    assert trust.PermitValidation is permits.PermitValidation


def test_receipts_facade_matches_service():
    assert trust.ReceiptService is receipts.ReceiptService
    assert trust.get_receipt_service is receipts.get_receipt_service
    assert trust.ReceiptError is receipts.ReceiptError


def test_idempotency_facade_matches_service():
    assert trust.IdempotencyService is idempotency.IdempotencyService
    assert trust.get_idempotency_service is idempotency.get_idempotency_service
    assert trust.IdempotencyConflictError is idempotency.IdempotencyConflictError
    assert trust.IdempotencyInProgressError is idempotency.IdempotencyInProgressError
    assert trust.IdempotencyReplay is idempotency.IdempotencyReplay


def test_audit_facade_matches_service():
    assert trust.verify_audit_chain is audit_chain.verify_audit_chain
    assert trust.sign_audit_model is audit_chain.sign_audit_model
    assert trust.audit_payload is audit_chain.audit_payload
    assert trust.AuditChainVerification is audit_chain.AuditChainVerification
    assert trust.record_audit_event is audit_log.record_audit_event


def test_policy_facade_matches_service():
    assert trust.evaluate_tool_invocation is decisions.evaluate_tool_invocation
    assert trust.evaluate_governed_action is decisions.evaluate_governed_action
    assert trust.PolicyDecision is decisions.PolicyDecision
    assert trust.evaluate_wallet_policy is policies.evaluate_wallet_policy
    assert trust.PolicyEvaluation is policies.PolicyEvaluation
    assert trust.record_governed_action is governance.record_governed_action


def test_metering_facade_matches_service():
    assert trust.AgentMoney is agent_money.AgentMoney
    assert trust.get_agent_money is agent_money.get_agent_money
    assert trust.InsufficientFundsError is agent_money.InsufficientFundsError
    assert trust.WalletNotFoundError is agent_money.WalletNotFoundError


def test_signing_facade_matches_service():
    assert trust.SigningKeyService is signing_keys.SigningKeyService
    assert trust.get_signing_key_service is signing_keys.get_signing_key_service
    assert trust.SigningKeyError is signing_keys.SigningKeyError
    assert trust.canonical_json is signing_keys.canonical_json
    assert trust.sha256_hex is signing_keys.sha256_hex


def test_adapter_seam_is_exposed():
    from app.trust.adapters import GovernedInvocationAdapter, McpGovernedAdapter

    assert trust.GovernedInvocationAdapter is GovernedInvocationAdapter
    assert trust.McpGovernedAdapter is McpGovernedAdapter
    assert issubclass(McpGovernedAdapter, GovernedInvocationAdapter)
    assert McpGovernedAdapter.protocol == "mcp"
