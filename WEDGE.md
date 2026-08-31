# Wedge: Transaction integrity for consequential autonomous actions

> **Make consequential agent actions transactional.**

On the supported governed upstream-MCP path, one logical action is bound to a
scoped permit and configured credit or call allowance, debited at most once when
admitted, given at most one gateway dispatch claim, and durably classified as
confirmed or uncertain. If delivery becomes uncertain, the gateway records
`delivery_uncertain` and never automatically redispatches.

```text
delegated authority → logical action identity → reserve configured allowance
→ debit → claim one gateway dispatch → confirmed outcome | delivery_uncertain
→ linked receipt/audit → reconcile
```

The claim ends at the gateway boundary. This is a durable transaction state
machine, not distributed ACID, and it does not prove an arbitrary upstream side
effect occurred exactly once. A remote side effect is exactly once only when
the upstream tool also honors the forwarded idempotency key.

An action belongs in this wedge only when it is:

- **Consequential:** a duplicate, incorrect, or uncertain mutation can cause
  material economic, operational, security, safety, or user harm.
- **Autonomous:** it is intended for agent execution under pre-delegated bounded
  authority, even if the current workflow remains read-only or human-gated
  until safe delegation is established.
- **Retry-sensitive:** repeating it after an unknown result can create a second
  or otherwise harmful effect.

## Positioning vs nearby products

Keep the surrounding systems. Enterprise IAM answers who may call. Gateways and
policy engines route, filter, and observe. Payment rails settle. Downstream
effect records remain the source of truth. This layer governs the transition
between bounded authority consumption and consequential execution.

| Nearby category | Keep it for | This layer adds |
|---|---|---|
| IAM / MCP authorization | Identity and allow/deny | Action-bound consumption and execution state |
| MCP gateways / policy / observability | Routing, policy, and traces | One-shot dispatch and explicit uncertainty |
| Payment rails / budget controls | Settlement and limits | Gateway-side configured accounting linkage |
| Receipt and log protocols | Evidence formats and observation | Runtime semantics that make the gateway record true |

Do not pitch as production payments, compliance-grade ledger, or IAM
replacement (see [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md)).

## Core User

Platform engineering, AI infrastructure, or security teams that keep
consequential writes read-only or human-gated because their current stack cannot
establish retry safety after an ambiguous dispatch.

## First Paid Use Case

One partner-owned, retry-sensitive staging mutation currently kept read-only or
human-gated because duplicate or ambiguous execution would matter.

The first design-partner motion should be that one real action behind the proxy,
not a broad migration of every agent workflow.

## Design Partner First Tool

Reference proof tool (local demo only): `trust-plane-echo` via
`make prove-trust-plane` / [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

Partner swap checklist:
[`docs/partner-first-tool-runbook.md`](docs/partner-first-tool-runbook.md).

Partner motion:

1. Keep `ENABLE_PROOF_SURFACES=false` in the partner environment.
2. Configure **one** internal Streamable HTTP MCP tool through the upstream
   environment variables (do not mount AWI/media/etc.).
3. Issue a wallet-scoped permit for that tool only.
4. Walk permit → invoke → charge → receipt → exact replay → changed-payload
   conflict → out-of-scope deny.
5. Let the partner tool commit one staging effect while its response is lost.
   Observe charged `delivery_uncertain`; replay the same logical action and
   prove there is no second gateway dispatch.
6. Have the partner engineer reconcile the actual effect from the partner's
   authoritative system and verify the gateway receipt offline.
7. Stop. Do not expand surface until that loop is trusted in their stack.

## What Is Core

- Logical action identity with changed-payload conflict.
- A persisted, one-shot gateway dispatch claim.
- Explicit `delivery_uncertain` with no automatic redispatch.
- Atomic permit-credit or call-allowance reservation where the supported
  backend provides it.
- Wallet-scoped API keys as a supporting identity mechanism.
- MCP discovery and invocation.
- Signed permits for tool scope, wallet binding, key binding, budget, expiry,
  and nonce.
- A request path for authority an agent cannot mint itself: the agent states
  scope, budget, and justification; a human decides; the middleware mints the
  permit from the reviewed terms.
- Signed, single-use price quotes that the metered charge honors, so an agent
  can know a call's cost before committing to it.
- Idempotency keys for permit issuance and governed invokes.
- Ledger-backed wallet charging as configured accounting support.
- Signed receipts for governed tool attempts as linked gateway evidence.
- Tamper-evident wallet audit chains as supporting evidence.
- Explicit denial reasons for out-of-scope or invalid governed attempts.
- A persisted remote-dispatch state that distinguishes confirmed outcomes from
  delivery uncertainty.

## What The Current Proof Shows

- A permit can bind one agent wallet to one allowed MCP tool and budget.
- A governed MCP invoke can validate that permit before the gateway dispatches
  the tool call.
- A successful governed invoke can charge the wallet and write a ledger entry.
- The response can include a signed receipt linked to permit, ledger, and audit
  identifiers.
- The audit chain can be verified after the fact.
- Replaying the same governed invoke can return the same receipt without a
  duplicate gateway dispatch or debit.
- A committed upstream dispatch claim cannot be reacquired.
- A post-claim timeout becomes charged `delivery_uncertain` and is not
  automatically redispatched.
- A request outside the permit scope can be denied with a concrete reason.
- An agent with no authority can ask a human for a scoped, budgeted permit, and
  the permit that gets minted carries exactly the terms the human reviewed.
- A signed quote can fix the price of one call, and the charge honors it even
  after the tool's registered price moves.

## What Is Proof Surface

AWI, browser automation, content generation, oracle crawls, media utilities,
IoT bridges, red-team services, RTaaS, telemetry auto-PR, and sandbox demos are
proof surfaces. They may exercise the control plane, but they do not define the
product until they consume the same permit, receipt, idempotency, and audit
primitives.

**Freeze list (do not expand):** [`docs/PROOF_SURFACES.md`](docs/PROOF_SURFACES.md)
— mirrors `PROOF_SURFACE_ROUTERS` in `app/main.py`, accept/freeze stubs, and
agent rules.

## What To Freeze

- New proof-surface features and ungated HTTP demos (see
  [`docs/PROOF_SURFACES.md`](docs/PROOF_SURFACES.md)).
- Broad multi-tool migrations before one partner tool is live.
- General-purpose IAM, policy engines, payment products, receipt standards,
  external witnessing, effect attestation, export connectors, KMS, settlement,
  transparency logs, and non-MCP adapters (see
  [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md)).

Production-like deploys must keep `ENABLE_PROOF_SURFACES=false`.
Deploy SOP (single path: `railway up` from this Dockerfile):
[`docs/deploy-railway.md`](docs/deploy-railway.md).

Agent-executable remediation of known spine/discovery/deploy debt:
[`docs/tech-debt-remediation-plan.md`](docs/tech-debt-remediation-plan.md).

## What Not To Claim Yet

- Production-ready payments or settlement.
- Compliance-grade ledger storage.
- Full autonomous economic actor infrastructure.
- Universal policy enforcement across every agent framework.
- Distributed exactly-once side effects in arbitrary upstream MCP servers.
- One atomic transaction with an upstream system.
- Proof that the downstream effect occurred.
- Generalized authority units beyond the configured credits, call allowance,
  and approval semantics the current path models.
- Unique ownership of signed receipts or generic agent governance.
- Quotes as a pricing or settlement product. A quote fixes what this gateway
  will debit from an internal wallet for one call; it is not a market price, a
  vendor commitment, or an invoice.
- Permit requests as an approval-workflow product. The decision is delegated to
  Sentinel and the surface is one ask and one poll — it is not a replacement
  for an access-request or change-management system.
- A replacement for enterprise IAM, secrets management, or sandbox isolation.
