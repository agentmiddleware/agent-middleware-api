# Elevator Pitch

Pitch copy for Agent Middleware API. Every claim here is bounded by
[`WEDGE.md`](WEDGE.md) and [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md).
If a version of this pitch ever outruns those two documents, the pitch is wrong,
not the documents.

---

## One line

> **Make consequential agent actions transactional.**

## Ten seconds

When an autonomous write times out after dispatch, retry may duplicate the
effect. Agent Middleware binds it to one logical action and bounded authority,
permits at most one gateway dispatch/debit, and records `delivery_uncertain`
instead of retrying blindly.

## Thirty seconds

When an agent's consequential write times out, can your current stack establish
whether retry is safe, preserve which authority was consumed, and prevent a
second gateway dispatch or debit while the downstream effect is still unknown?

Agent Middleware API is a transaction-integrity boundary for consequential MCP
actions. An agent uses a wallet-scoped key and an Ed25519-signed permit bound to
tool, scope, budget, and expiry. The gateway records one logical action, returns
the original result and signed receipt on an identical replay, rejects changed
input under that key, and never automatically redispatches a post-claim
ambiguous call. Out-of-scope and over-budget calls fail before a debit.

Run the executable proof locally, then evaluate the supported vendor-managed,
single-tenant pilot with one real internal tool.

## Two minutes (design-partner version)

**The problem to test.** Give me one consequential write you keep read-only or
human-gated. If its effect commits and the response disappears, can you tell
whether retry is safe, which authority was consumed, and what evidence survives?
Existing IAM, gateway, downstream idempotency, effect lookup, or logging may
already be sufficient; the first conversation must establish that they are not
before this product is proposed.

**The wedge.** Not a general MCP gateway, and not payments. The narrow,
differentiating primitive is **durable transaction semantics for consequential
execution at the gateway boundary**:

```text
delegated authority → logical action identity → reserve configured allowance
→ debit → claim one gateway dispatch → confirmed outcome | delivery_uncertain
→ linked receipt/audit → reconcile
```

This is a gateway state machine, not one distributed ACID transaction and not
proof that the downstream effect occurred.

**What that buys you.**

- **Bounded authority consumption.** Configured credits or call allowance—and,
  where enabled, one single-use approval—are bound to the action. Decimal wallet
  balances use row-locked debits; final permit checks and reservation happen
  while the permit row is locked, so competing invokes and revoke-versus-invoke
  races resolve correctly.
- **One logical action.** A repeated idempotency key returns the original
  result and receipt with no second gateway dispatch and no second debit. One
  persisted chain links the idempotency record, permit reservation, ledger
  debit, dispatch attempt, receipt, and audit event.
- **Honest ambiguity.** Confirmed pre-dispatch failures and
  upstream-returned errors are refunded and receipted. Genuinely ambiguous
  post-dispatch outcomes are marked `delivery_uncertain` and routed to
  fail-closed manual review — never silently redispatched.
- **Linked gateway evidence.** Signed receipts for success, denial, *and*
  failure, linked where applicable to permits, ledger entries, dispatch state,
  and a verifiable per-wallet hash chain. This is not a compliance-grade ledger
  or proof of physical work.

**Why believe it.** The proof is executable, not asserted:

| Command | What it proves |
|---|---|
| `make prove-trust-plane` | The full permit → invoke → charge → receipt → replay → deny loop |
| `make dogfood-trust-plane` | The same loop against a tool with a real on-disk side effect |
| `make prove-crash-recovery` | Crash consistency across two OS processes killed at commit boundaries |
| `make red-team-trust-plane` | Adversarial attempts against the boundary |

**The ask.** One partner-owned agent, one real staging tool, and one partner
engineer behind the proxy. Test exact replay and changed input, then let the
tool commit one staging effect while its response is lost. Confirm
`delivery_uncertain` and no gateway redispatch, have the partner engineer
reconcile the actual effect, and verify the receipt offline. If removing the
boundary would not restore an unacceptable risk or earn a commercial next
step, stop.

---

## Positioning in one table

| Nearby category | Keep it for | This layer adds |
|---|---|---|
| IAM / MCP authorization | Identity and allow/deny | Action-bound consumption and execution state |
| MCP gateways | Routing, policy, and traces | One-shot dispatch and explicit uncertainty |
| Payment rails | Settlement | Gateway-side configured accounting linkage |
| Receipt/log protocols | Evidence format and observation | Runtime semantics that make the gateway record true |

## Who it's for

Platform engineering, AI infrastructure, or security teams that already run
internal agents against MCP-style tools and need a control point *before* the
tool is invoked — and who can bring one real tool to the first conversation.

## Objections, answered honestly

**"Isn't this just an API gateway?"** A gateway answers whether a call is
allowed. This binds the authorization to an internal credit budget and signed
receipt, and prevents an identical replay under the same accepted key from
creating another gateway dispatch or debit. The product is the durable
action/dispatch/uncertainty state machine; permits, debits, receipts, and audit
records are linked mechanisms and evidence.

**"We already have IAM."** Keep it. This is not an IAM replacement and does not
try to be. IAM says an agent may call a tool; this bounds one action's
configured authority or allowance and its behavior under uncertainty.

**"Can't we just log tool calls?"** Logs are written by the same system that
made the call and can be rewritten by anyone with database access. Receipts are
signed and chained, so tampering is *evident*. (Evident, not impossible — a
database administrator who can alter both the data and its chain metadata is
inside the trust boundary, and we say so.)

**"Does exactly-once really hold across the network?"** For one accepted
idempotency key at our boundary: at most one gateway dispatch/debit, plus one
terminal receipt when the supported path reaches a receiptable terminal
disposition. A *remote* tool's own side effect is exactly once only if that tool
also honors the forwarded key. Anything broader would overstate the
distributed-systems guarantee.

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
- One atomic transaction with an upstream system.
- Proof of the actual downstream effect.
- Unique ownership of signed receipts or generic agent governance.
- A replacement for enterprise IAM, secrets management, or sandbox isolation.
- Byzantine fault tolerance. There is one server, one database, and one
  operator-held signing key — there are no replicas and no consensus.

Refusing to overclaim is the product's defining discipline. The pitch inherits
it.
