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

## Atomicity — one real transaction, not a saga

`POST /v1/pods` runs as a single database transaction: the sponsor wallet
and every member's agent wallet and key are all written through the same
open session, committed once. `WalletEngine.create_sponsor_wallet`,
`WalletEngine.create_agent_wallet`, and `APIKeyService.create_key` each
accept an optional `session` parameter for exactly this — when given, they
add/flush against it and never begin or commit it themselves, so
`PodService.create_pod` (the caller) is the only place that decides commit
vs. rollback. This is additive: every existing standalone caller of those
three methods is unaffected, since omitting `session` preserves the
original open-commit-close-your-own-session behavior unchanged.

- The common failure mode — a caller requesting member budgets that don't
  fit inside the pod total — is still checked **before** the transaction
  even opens, so it never touches the database.
- A genuine failure *during* member provisioning (a transient DB error, an
  unexpected insufficient-funds race, anything) rolls the whole transaction
  back automatically. There is no partial pod: not the sponsor wallet, not
  any member wallet, not any key. The error response
  (`pod_provisioning_failed` or `insufficient_funds`) says which member was
  being provisioned when it failed, purely for diagnosis — an operator has
  nothing to clean up or finish, because nothing was left behind.

This was previously a documented limitation (application-level partial
state on failure); it is now closed at the source, not worked around.

## Why this is a dormant trust surface, not a mounted one

`AGENTS.md`'s business invariant: *no new core capability without
documented evidence from a named prospective customer.* Pods are a new
core capability. Until a named design partner has a concrete use for it,
this stays in `DORMANT_TRUST_ROUTERS` in `app/main.py` — implemented and
tested, mounted only when `ENABLE_PROOF_SURFACES=true`, not advertised in
`/.well-known/agent.json` or `/v1/discover` in production. See
`docs/PROOF_SURFACES.md` for the general pattern this follows.
