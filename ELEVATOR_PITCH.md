# Elevator Pitch

Pitch copy for Agent Middleware API. Every claim here is bounded by
[`WEDGE.md`](WEDGE.md) and [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md).
If a version of this pitch ever outruns those two documents, the pitch is wrong,
not the documents.

---

## One line

> **Authorize one agent action. Charge it once. Prove what happened.**

## Ten seconds

Your agent invokes a costly tool and the request times out. Agent Middleware
puts one scoped, budgeted boundary in front of the call: replaying the same
request and accepted idempotency key cannot create another gateway dispatch or
debit, and the terminal gateway outcome gets a signed receipt.

## Thirty seconds

When an agent's tool call times out, can your current stack prove whether it was
authorized and dispatched, prevent the retry from creating another debit, and
show the economic consequence afterward?

Agent Middleware API is a transaction boundary for metered MCP calls. An agent
uses a wallet-scoped key and an Ed25519-signed permit bound to tool, scope,
budget, and expiry. The gateway records one accepted request key, returns the
original result and signed receipt on an identical replay, and rejects changed
input under that key. Out-of-scope and over-budget calls fail before a debit.

Run the executable proof locally, then evaluate the supported vendor-managed,
single-tenant pilot with one real internal tool.

## Two minutes (design-partner version)

**The problem to test.** Give me one tool you are afraid to let an autonomous
agent invoke. If the call times out, can you tell whether the gateway dispatched
it, whether a retry creates another debit, who authorized the economic exposure,
and what evidence survives afterward? Existing IAM, gateway, or logging controls
may already be sufficient; the first conversation must establish that they are
not before this product is proposed.

**The wedge.** Not a general MCP gateway, and not payments. The narrow,
differentiating primitive is **exactly-once economic authorization at the
gateway boundary**:

```text
scoped signed permit -> governed MCP invoke -> wallet charge -> signed receipt
-> ledger -> audit chain -> replay no double charge -> out-of-scope denial
```

**What that buys you.**

- **Budgets that bind.** Decimal wallet balances with row-locked debits. Final
  permit checks and budget reservation happen while the permit row is locked,
  so competing invokes and revoke-versus-invoke races resolve correctly.
- **Charge-once under failure.** A repeated idempotency key returns the original
  result and receipt with no second gateway dispatch and no second debit. One
  persisted chain links the idempotency record, permit reservation, ledger
  debit, dispatch attempt, receipt, and audit event.
- **Honest failure accounting.** Confirmed pre-dispatch failures and
  upstream-returned errors are refunded and receipted. Genuinely ambiguous
  post-dispatch outcomes are marked `delivery_uncertain` and routed to
  fail-closed manual review — never silently redispatched.
- **Portable gateway evidence.** Signed receipts for success, denial, *and*
  failure, linked to permits, ledger entries, and a verifiable per-wallet hash
  chain. This is not a compliance-grade ledger or proof of physical work.

**Why believe it.** The proof is executable, not asserted:

| Command | What it proves |
|---|---|
| `make prove-trust-plane` | The full permit → invoke → charge → receipt → replay → deny loop |
| `make dogfood-trust-plane` | The same loop against a tool with a real on-disk side effect |
| `make prove-crash-recovery` | Crash consistency across two OS processes killed at commit boundaries |
| `make red-team-trust-plane` | Adversarial attempts against the boundary |

**The ask.** One partner-owned agent, one real staging tool, and one partner
engineer behind the proxy. Intentionally retry the action, verify the receipt
in the partner's environment, and ask whether removing the boundary would
restore an unacceptable risk. If it does not earn a commercial next step, stop.

---

## Positioning in one table

| Nearby category | Their center of gravity | Our difference |
|---|---|---|
| MCP trust gateways | Policy and evidence | Wallet debit plus economic idempotency |
| MCP monetization / pay-per-tool | Payment rails | Internal budgets, no settlement claim |
| Enterprise authz for MCP | Who may call | Meter, receipt, and charge exactly once |

## Who it's for

Platform engineering, AI infrastructure, or security teams that already run
internal agents against MCP-style tools and need a control point *before* the
tool is invoked — and who can bring one real tool to the first conversation.

## Objections, answered honestly

**"Isn't this just an API gateway?"** A gateway answers whether a call is
allowed. This binds the authorization to an internal credit budget and signed
receipt, and prevents an identical replay under the same accepted key from
creating another gateway dispatch or debit. The debit and receipt are the
product; the policy check is table stakes.

**"We already have IAM."** Keep it. This is not an IAM replacement and does not
try to be. IAM says an agent may call a tool; this bounds how much that agent
may spend doing it and produces the evidence afterward.

**"Can't we just log tool calls?"** Logs are written by the same system that
made the call and can be rewritten by anyone with database access. Receipts are
signed and chained, so tampering is *evident*. (Evident, not impossible — a
database administrator who can alter both the data and its chain metadata is
inside the trust boundary, and we say so.)

**"Does exactly-once really hold across the network?"** For one accepted
idempotency key at our boundary: one gateway dispatch, one debit, one receipt.
A *remote* tool's own side effect is exactly once only if that tool also honors
the forwarded key. Anything broader would overstate the distributed-systems
guarantee.

**"What's the maturity?"** Production beta, not production complete. Run the
proofs locally; the supported design-partner posture is vendor-managed and
single-tenant. Read `SECURITY_LIMITATIONS.md` before deciding.

## What this pitch must never claim

Do not say, imply, or let a slide suggest:

- Production-ready payments or settlement.
- Compliance-grade ledger storage.
- Full autonomous-economic-actor infrastructure.
- Universal policy enforcement across every agent framework.
- Distributed exactly-once side effects in arbitrary upstream MCP servers.
- A replacement for enterprise IAM, secrets management, or sandbox isolation.
- Byzantine fault tolerance. There is one server, one database, and one
  operator-held signing key — there are no replicas and no consensus.

Refusing to overclaim is the product's defining discipline. The pitch inherits
it.
