"""
Agent Well-Known Router — Phase 9
=================================
Project agent discovery endpoints following common web conventions.

Implements /.well-known/agent.json for agent directory registration.
Product capabilities are the MCP trust-plane wedge; AWI and related
workloads are labeled proof surfaces (often simulated) and must not be
read as production-complete features.
"""

import base64
import binascii
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.config import get_settings, public_api_origin
from ..core.public_contact import validated_public_contact
from ..schemas.awi import AWIDiscoveryManifest, AWIRepresentationType
from ..services.awi_action_vocab import get_awi_vocabulary
from ..services.signing_keys import (
    RECEIPT_CANONICALIZATION,
    SigningKeyError,
    get_signing_key_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Agent Discovery"])

# Module alias for tests that monkeypatch settings (see test_production_trust_posture).
settings = get_settings()

# Trust-plane product capabilities (governed MCP wedge).
PRODUCT_CAPABILITIES: list[str] = [
    "billing",
    "mcp_tools",
    "permits",
    "receipts",
    "audit",
    "policies",
    "signing_keys",
    "api_keys",
]

# Proof-surface catalog — present for discovery honesty, not as product claims.
PROOF_SURFACE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "awi_automation",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": (
            "HTTP AWI routes bypass the permit→receipt loop unless invoked "
            "as governed MCP tools."
        ),
    },
    {
        "id": "passkey_auth",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": (
            "WebAuthn may use WEBAUTHN_ALLOW_MOCK in tests; production-like "
            "boots refuse mock verification."
        ),
    },
    {
        "id": "dom_bridge",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Playwright DOM bridge is a proof surface, not a production isolation boundary.",
    },
    {
        "id": "rag_memory",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Embeddings may fall back to mock vectors when no embedding provider is configured.",
    },
    {
        "id": "telemetry",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Autonomous PM / auto-PR paths are simulation-gated by default.",
    },
    {
        "id": "agent_communication",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Webhook delivery is simulated until SIMULATION_MODE_AGENT_COMMS is flipped with a real client.",
    },
    {
        "id": "sandbox_testing",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "Sandboxes are dry-run / demo surfaces, not compliance isolation.",
    },
    {
        "id": "ai_decision_making",
        "status": "proof_surface",
        "simulation": True,
        "governed_by_permits": False,
        "note": "AI decide/heal endpoints are proof surfaces adjacent to the trust wedge.",
    },
]


def get_agent_first_metadata() -> dict[str, Any]:
    """
    Single source of truth for agent-first bootstrap hints.
    Used by /.well-known/agent.json and GET /v1/discover.
    """
    cfg = get_settings()
    bootstrap = [
        "/.well-known/agent.json",
        "/llms.txt",
        "/mcp/tools.json",
        "/openapi.json",
    ]
    if cfg.ENABLE_PROOF_SURFACES:
        # Insert AWI manifest after agent.json when proof surfaces are mounted.
        bootstrap.insert(1, "/.well-known/awi.json")

    return {
        "primary_audience": "autonomous_agents",
        "design_principle": "agent_first",
        "product_wedge": "governed_mcp_trust_plane",
        "product_loop": [
            "discover",
            "authenticate",
            "authorize",
            "invoke",
            "meter",
            "receipt",
            "audit",
            "govern",
        ],
        "bootstrap_sequence": bootstrap,
        "simulation_and_dependency_truth": "/health/dependencies",
        "proof_surfaces_enabled": bool(cfg.ENABLE_PROOF_SURFACES),
        "proof_surface_note": (
            "Entries under proof_surfaces are demo/workload scaffolding. "
            "They do not define the product unless they consume the same "
            "permit, receipt, idempotency, and audit primitives via governed MCP."
        ),
        "human_observability": {
            "human_dashboard_url": "/dashboard",
            "interactive_docs_url": "/docs",
            "redoc_url": "/redoc",
            "note": (
                "The public /dashboard is a status and evidence index. "
                "Authenticated tenant inspection remains API-only."
            ),
        },
    }


def _provider_manifest(config: Any) -> dict[str, str]:
    """Expose an accountable provider only when the full contact gate passes."""

    contact = validated_public_contact(config)
    if contact is None:
        return {"status": "contact_not_configured"}
    return {
        "name": contact["name"],
        "email": contact["email"],
        "website": contact["url"],
    }


def _authentication_manifest() -> dict[str, Any]:
    """Honest auth discovery: no public self-serve key mint."""
    return {
        "type": "api_key",
        "header": "X-API-Key",
        "public_self_serve": False,
        "bootstrap_docs": "/docs/partner-api-key-bootstrap.md",
        "note": (
            "No public self-serve API key mint. An operator bootstrap/admin "
            "key (VALID_API_KEYS) provisions wallets and DB-scoped agent keys. "
            "Agents must use a wallet-scoped key — see bootstrap_docs."
        ),
    }


def _local_try_it_manifest() -> dict[str, Any]:
    """Credential-free proof path for agents evaluating the trust loop."""
    return {
        "mode": "local_self_hosted",
        "repository": "https://github.com/PetrefiedThunder/agent-middleware-api",
        "command": "make prove-trust-plane",
        "live_access": "operator_issued",
        "requires_live_credentials": False,
        "proves": [
            "scoped_permit",
            "metered_mcp_invoke",
            "signed_receipt",
            "replay_without_second_charge",
            "out_of_scope_denial",
            "offline_receipt_verification",
        ],
        "note": (
            "Runs the real FastAPI trust path against a throwaway local SQLite "
            "database. This is a reproducible proof, not a production or "
            "settlement claim."
        ),
    }


class AgentPluginManifest(BaseModel):
    """Project discovery manifest; this is not an A2A Agent Card."""

    schema_version: str = Field(default="1.0", description="Manifest schema version")
    name: str = Field(description="Service/plugin name")
    description: str = Field(description="What this service provides")
    version: str = Field(description="Current version")
    canonical_api: str = Field(
        default="",
        description=(
            "Absolute public API origin from PUBLIC_URL. Empty when unset — "
            "do not invent localhost as the canonical base."
        ),
    )
    provider: dict = Field(default_factory=lambda: {"status": "contact_not_configured"})

    capabilities: list[str] = Field(
        default_factory=lambda: list(PRODUCT_CAPABILITIES),
        description=(
            "Trust-plane product capability identifiers (MCP permit→meter→"
            "receipt→audit wedge). Proof surfaces are listed separately."
        ),
    )

    proof_surfaces: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Labeled non-product workloads. Treat as simulated/demo unless "
            "invoked through governed MCP with permits."
        ),
    )

    endpoints: dict = Field(description="API endpoints")

    authentication: dict = Field(default_factory=_authentication_manifest)

    try_it: dict[str, Any] = Field(
        default_factory=_local_try_it_manifest,
        description=(
            "Credential-free local proof for autonomous clients evaluating "
            "the governed permit-to-receipt loop."
        ),
    )

    pricing: dict = Field(
        default_factory=lambda: {
            "model": "controlled_design_partner_pilot",
            "public_pricing": False,
            "public_sla": False,
            "note": "Credits and credentials are provisioned by an operator.",
        }
    )

    integrations: dict = Field(
        default_factory=lambda: {
            # Release artifacts are built from this repository; neither SDK is
            # advertised as a package-registry install.
            "python_sdk": {
                "status": "release_artifact_only",
                "version": "0.4.0",
                "path": "b2a_sdk/",
                "install": "pip install -e ./b2a_sdk",
                "note": (
                    "Wheel and sdist are attached to python-sdk-v0.4.0 by the "
                    "release workflow. Not published to PyPI."
                ),
            },
            "typescript_sdk": {
                "status": "not_published",
                "note": (
                    "No published TypeScript SDK. Use HTTP "
                    "(/mcp, /v1/permits, /v1/receipts)."
                ),
            },
            "mcp": True,
            "preferred_integration": "http_mcp",
            "langgraph": "in_repo_wrapper",
            "crewai": "in_repo_wrapper",
            "autogen": "in_repo_wrapper",
            "llamaindex": "in_repo_wrapper",
        }
    )

    documentation: dict = Field(
        default_factory=lambda: {
            "human_dashboard": "/dashboard",
            "api_reference": "/docs",
            "openapi": "/openapi.json",
            "llm_readable": "/llm.txt",
            "llms_readable": "/llms.txt",
            "wedge": "/WEDGE.md",
            "security_limitations": "/SECURITY_LIMITATIONS.md",
            "partner_guide": "/DESIGN_PARTNER_GUIDE.md",
            "partner_api_key_bootstrap": "/docs/partner-api-key-bootstrap.md",
            "agent_accountability": "/docs/agent-accountability.md",
        }
    )

    agent_first: dict[str, Any] = Field(
        default_factory=get_agent_first_metadata,
        description=(
            "How autonomous clients should treat this service: discovery order, "
            "authority for simulation vs real behavior, and product wedge scope."
        ),
    )


def _product_endpoints() -> dict[str, str]:
    return {
        "api_base": "/v1",
        "discovery": "/v1/discover",
        "mcp": "/mcp",
        "billing": "/v1/billing",
        "permits": "/v1/permits",
        "receipts": "/v1/receipts",
        "audit": "/v1/audit",
        "policies": "/v1/policies",
        "evidence": "/v1/evidence",
        # Mounted prefix is /v1/signing-keys; "/v1/keys" was advertised for a
        # while and resolved to nothing, so discovery clients 404'd on it.
        "keys": "/v1/signing-keys",
        "trust_keys": "/.well-known/trust-keys.json",
        "api_keys": "/v1/api-keys",
        "me": "/v1/me",
        "health": "/health",
        "agent_manifest": "/.well-known/agent.json",
        "llm_docs": "/llm.txt",
        "llms_docs": "/llms.txt",
        "dependency_truth": "/health/dependencies",
    }


def _proof_surface_endpoints() -> dict[str, str]:
    return {
        "awi": "/v1/awi",
        "awi_passkey": "/v1/awi/passkey",
        "awi_dom": "/v1/awi/dom",
        "awi_rag": "/v1/awi/rag",
        "telemetry": "/v1/telemetry",
        "comms": "/v1/comms",
        "ai": "/v1/ai",
        "awi_manifest": "/.well-known/awi.json",
    }


def _build_agent_manifest() -> AgentPluginManifest:
    """Build the bootstrap manifest with an honest product vs proof split."""
    endpoints = _product_endpoints()
    proof_surfaces = list(PROOF_SURFACE_CATALOG)
    documentation = {
        "human_dashboard": "/dashboard",
        "api_reference": "/docs",
        "openapi": "/openapi.json",
        "llm_readable": "/llm.txt",
        "llms_readable": "/llms.txt",
        "wedge": "/WEDGE.md",
        "security_limitations": "/SECURITY_LIMITATIONS.md",
        "partner_guide": "/DESIGN_PARTNER_GUIDE.md",
        "partner_api_key_bootstrap": "/docs/partner-api-key-bootstrap.md",
        "agent_accountability": "/docs/agent-accountability.md",
    }

    cfg = get_settings()
    if cfg.ENABLE_PROOF_SURFACES:
        endpoints = {**endpoints, **_proof_surface_endpoints()}
        documentation = {
            **documentation,
            "awi_guide": "/docs/awi-adoption-guide.md",
            "phase9_passkey": "/v1/awi/passkey/register",
            "phase9_dom_bridge": "/v1/awi/dom/snapshot",
            "phase9_rag": "/v1/awi/rag/ingest",
        }
    else:
        proof_surfaces = [
            {
                **entry,
                "mounted": False,
                "note": (f"{entry['note']} Not mounted (ENABLE_PROOF_SURFACES=false)."),
            }
            for entry in proof_surfaces
        ]

    return AgentPluginManifest(
        name="agent-middleware-api",
        description=(
            "Governed MCP trust plane for autonomous agents: scoped permits, "
            "metered tool invocation, signed receipts, and wallet audit chains. "
            "Additional routers are labeled proof surfaces, not the product wedge."
        ),
        version=cfg.APP_VERSION,
        canonical_api=public_api_origin(),
        provider=_provider_manifest(cfg),
        capabilities=list(PRODUCT_CAPABILITIES),
        proof_surfaces=proof_surfaces,
        endpoints=endpoints,
        authentication=_authentication_manifest(),
        documentation=documentation,
        agent_first=get_agent_first_metadata(),
    )


def build_awi_manifest() -> dict[str, Any]:
    """Build the AWI-over-MCP discovery manifest."""
    vocabulary = get_awi_vocabulary()
    actions = [action.to_public_dict() for action in vocabulary.list_all_actions()]

    return {
        "schema_version": "0.1.0",
        "awi_version": "0.1.0-draft",
        "status": "draft",
        "profile": "awi-over-mcp",
        "surface": "proof_surface",
        "transport": {
            "primary": "http",
            "mcp_compatible": True,
            "mcp_manifest": "/.well-known/mcp/tools.json",
        },
        "description": (
            "Proof-surface AWI semantics exposed beside the governed MCP "
            "trust plane. Prefer MCP tools with permits for metered, "
            "receipted automation."
        ),
        "endpoints": {
            "sessions": "/v1/awi/sessions",
            "execute": "/v1/awi/execute",
            "represent": "/v1/awi/represent",
            "intervene": "/v1/awi/intervene",
            "vocabulary": "/v1/awi/vocabulary",
            "queue_status": "/v1/awi/queue/status",
            "audit_events": "/v1/audit/events",
            "audit_chain_verification": "/v1/audit/verify-chain",
            "openapi": "/openapi.json",
        },
        "representation_types": [item.value for item in AWIRepresentationType],
        "actions": actions,
        "safety_capabilities": {
            "wallet_scoped_authorization": True,
            "human_intervention": ["pause", "resume", "steer"],
            # Advertised as available on the proof surface; see known_limitations
            # for mock/production-like constraints and MCP-only permit path.
            "passkey_high_risk_actions": True,
            "signed_permits": True,
            "tamper_evident_audit_chain": True,
            "sensitive_parameter_redaction": True,
        },
        "known_limitations": [
            "This is an AWI semantics profile over MCP/HTTP, not a standalone AWI wire standard.",
            "HTTP AWI routes are a proof surface and do not enforce permits/receipts unless the call goes through governed MCP.",
            "Passkey verification fails closed without py_webauthn; WEBAUTHN_ALLOW_MOCK is refused in production-like environments.",
            "The login action is provisional; credential_handle is preferred over plaintext credentials.",
            "click_button and scroll are compatibility actions, not pure semantic actions.",
            "Representation efficiency benchmarks are local and deterministic until external WebArena-style evaluation is added.",
            "Sandbox and browser automation are not production isolation boundaries.",
        ],
    }


@router.get(
    "/.well-known/agent.json",
    summary="Agent Discovery Manifest",
    description=(
        "Returns this project's agent bootstrap manifest for discovery clients. "
        "It is not an A2A Agent Card. Product capabilities are the MCP trust "
        "plane; proof_surfaces are labeled demo/workload scaffolding."
    ),
    responses={
        200: {"description": "Project agent bootstrap manifest"},
    },
)
async def get_agent_json(request: Request):
    """
    Serve the agent.json manifest.

    This preserves the project's established /.well-known/agent.json
    convention. It is not the current A2A agent-card.json format.
    """
    manifest = _build_agent_manifest()
    return JSONResponse(
        content=manifest.model_dump(mode="json"),
        media_type="application/json",
    )


@router.get(
    "/.well-known/awi.json",
    response_model=AWIDiscoveryManifest,
    summary="AWI Discovery Manifest",
    description=(
        "Returns the draft AWI-over-MCP manifest with action vocabulary, "
        "representation types, endpoints, safety capabilities, and known limits. "
        "Marked as a proof surface — not the product wedge."
    ),
)
async def get_awi_json():
    """Serve the draft AWI-over-MCP manifest (only when proof surfaces are on)."""
    if not get_settings().ENABLE_PROOF_SURFACES:
        return JSONResponse(
            status_code=404,
            content={
                "error": "awi_manifest_unmounted",
                "detail": (
                    "AWI is a proof surface and is not mounted "
                    "(ENABLE_PROOF_SURFACES=false). Use /.well-known/agent.json "
                    "and /mcp/tools.json for the trust-plane wedge."
                ),
            },
        )
    return JSONResponse(content=build_awi_manifest(), media_type="application/json")


def _b64_to_b64url(value: str) -> str | None:
    """Re-encode standard base64 key material as unpadded base64url for JWK."""
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _published_key(key: Any) -> dict[str, Any]:
    """Project one signing key into its public, verifier-facing shape."""
    entry: dict[str, Any] = {
        "kid": key.key_id,
        "alg": key.alg,
        "status": key.status,
        "public_key_b64": key.public_key_b64,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "activated_at": key.activated_at.isoformat() if key.activated_at else None,
        "retired_at": key.retired_at.isoformat() if key.retired_at else None,
    }
    # JWK mirror for callers using an off-the-shelf JOSE library. Ed25519 lives
    # in the OKP key type; `x` is the raw 32-byte public key as base64url.
    x = _b64_to_b64url(key.public_key_b64)
    if x is not None and key.alg == "Ed25519":
        entry["jwk"] = {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": x,
            "kid": key.key_id,
            "alg": "EdDSA",
            "use": "sig",
        }
    return entry


def _trust_keys_unavailable() -> JSONResponse:
    """Refuse rather than publish a key set a verifier cannot use.

    An empty ``keys`` list is not a neutral answer. A verifier looking up the
    ``kid`` on a receipt would find nothing and, depending on how strictly it
    is written, report the receipt as unverifiable — which reads as a forgery.
    Serving 503 keeps that situation in the "cannot tell, ask again" bucket
    where it belongs.
    """
    return JSONResponse(
        status_code=503,
        content={
            "error": "trust_keys_unavailable",
            "detail": (
                "No usable signing key is published right now. Treat receipts "
                "as unverified-pending, not invalid, and retry."
            ),
        },
    )


@router.get(
    "/.well-known/trust-keys.json",
    summary="Trust-Plane Public Signing Keys",
    description=(
        "Unauthenticated publication of the Ed25519 public keys this plane "
        "signs receipts, permits, and audit events with. Deliberately open: a "
        "receipt is only portable evidence if someone who holds no credential "
        "here can still check its signature. Retired keys stay listed so "
        "historical receipts remain verifiable; disabled keys are withheld "
        "because the plane itself refuses to verify against them."
    ),
)
async def get_trust_keys_json():
    """Serve the public verification keys for offline receipt checking."""
    service = get_signing_key_service()
    try:
        # Materialize the active key so a freshly deployed plane publishes a
        # usable key rather than an empty list.
        await service.ensure_active_key()
    except (SigningKeyError, RuntimeError):
        # Misconfigured or absent signing material must not take down public
        # verification of receipts already signed under earlier keys.
        logger.warning("trust_keys_active_key_unavailable", exc_info=True)

    try:
        keys = await service.list_public_keys()
    except (SigningKeyError, RuntimeError):
        logger.warning("trust_keys_unavailable", exc_info=True)
        return _trust_keys_unavailable()

    if not keys:
        # Reachable store, nothing publishable — e.g. signing material is
        # misconfigured so ensure_active_key() failed above, or every stored
        # key has been disabled. Same situation for a verifier as an
        # unreachable store, so it gets the same answer.
        logger.warning("trust_keys_empty")
        return _trust_keys_unavailable()

    return JSONResponse(
        content={
            "schema_version": "1.0",
            "issuer": public_api_origin(),
            "alg": "Ed25519",
            "canonicalization": RECEIPT_CANONICALIZATION,
            "keys": [_published_key(key) for key in keys],
            "verification": {
                "portable_receipt": "/v1/receipts/{receipt_id}/portable",
                "note": (
                    "Verify signature over the bundle's `signing_input` bytes "
                    "with the key whose `kid` matches. Reading a receipt "
                    "requires authorization; verifying one you were given "
                    "does not."
                ),
            },
        },
        media_type="application/json",
    )


@router.get(
    "/.well-known/mcp/tools.json",
    summary="MCP Tools Manifest",
    description="Compatibility mirror of the project's public MCP-shaped tool list.",
)
async def get_mcp_tools_json():
    """
    Serve a compatibility mirror of the project's tool metadata.

    Conformant MCP servers expose tool discovery through ``tools/list`` rather
    than through a well-known JSON document.
    """
    from .mcp import build_mcp_tools_manifest

    return JSONResponse(content=await build_mcp_tools_manifest())
