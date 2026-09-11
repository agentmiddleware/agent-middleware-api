# Pods

A pod is a named group of agent API keys under one shared budget:
one sponsor wallet holds the pod's total credits, and each member is an
ordinary agent wallet with its own wallet-scoped API key, provisioned from
that sponsor in a single `POST /v1/pods` call.

## What this is

`app/services/pods.py` composes three existing, tested primitives —
`AgentMoney.create_sponsor_wallet`, `AgentMoney.create_agent_wallet`, and
`APIKeyService.create_key` — and adds one thing: a `pod_name` and a
`kind: "pod"` metadata tag on the sponsor wallet, so a pod can be told apart
from an ordinary sponsor wallet later. No new ledger, no new auth model, no
new key format.

- `POST /v1/pods` — bootstrap-admin only. Creates the pod's shared-budget
  wallet, then one agent wallet + key per member, in one call. Member
  budgets can be set explicitly or left to split the pod total evenly.
  Fails with `pod_budget_exceeded` (422) *before creating anything* if
  explicit member budgets already exceed the pod total.
- `GET /v1/pods/{pod_id}` — bootstrap-admin only. Aggregate budget status:
  total, what's still unallocated at the pod level, and each member's
  balance. Never returns key material.

## What this deliberately is not (yet)

- **No department templates.** A pod is a flat list of members you name
  yourself. There is no "outreach" or "research" template that provisions
  role-specific tooling or permits — that's a product decision for a real
  pilot to define, not something to invent speculatively.
- **No on-demand spin-up trigger.** Members are created at pod-creation
  time, not spawned by an agent action. A pod does not currently spin up
  a new department in response to anything.
- **No cross-pod budget sharing or reclaim flow.** Each pod's budget is
  its own sponsor wallet; there is no mechanism here for moving credits
  between pods, or for automatically reclaiming an idle member's unspent
  budget back to the pod (an operator can still do this by hand via the
  existing billing endpoints, since a pod's wallets are ordinary wallets).
- **No email inboxes.** "Pod" here is strictly the budget/key grouping.
  It has no relationship to email, inbound or outbound.

## Atomicity — read this before assuming "one call" means "one transaction"

Each underlying call (`create_sponsor_wallet`, `create_agent_wallet`,
`create_key`) is its own database transaction; that's how the existing
wallet engine already works, and this module does not add cross-call
distributed-transaction machinery on top of it.

- The common failure mode — a caller requesting member budgets that don't
  fit inside the pod total — is checked **before** anything is created, so
  it never leaves partial state.
- A genuine failure *during* member provisioning (a transient DB error
  after member 1 of 3 succeeded, say) leaves a partial pod: the sponsor
  wallet and the members already created are real, spendable wallets. The
  error response (`pod_partially_provisioned`, 500) names the pod id, which
  members completed, and which one failed, so an operator can inspect or
  finish the pod rather than losing track of the partial state silently.

## Why this is a dormant trust surface, not a mounted one

`AGENTS.md`'s business invariant: *no new core capability without
documented evidence from a named prospective customer.* Pods are a new
core capability. Until a named design partner has a concrete use for it,
this stays in `DORMANT_TRUST_ROUTERS` in `app/main.py` — implemented and
tested, mounted only when `ENABLE_PROOF_SURFACES=true`, not advertised in
`/.well-known/agent.json` or `/v1/discover` in production. See
`docs/PROOF_SURFACES.md` for the general pattern this follows.
