# Elevator Pitch

Pitch copy for Agent Middleware API. Every claim here is bounded by
[`WEDGE.md`](WEDGE.md) and [`SECURITY_LIMITATIONS.md`](SECURITY_LIMITATIONS.md).
If a version of this pitch ever outruns those two documents, the pitch is wrong,
not the documents.

---

## One line

> **Authorize one agent action. Charge it once. Prove what happened.**

## Ten seconds

Agent Middleware API is a self-hostable trust plane that sits between your
autonomous agents and the MCP tools they call. Every call needs a signed,
scoped permit, gets metered against a wallet budget, and returns a signed
receipt on a tamper-evident audit chain — and a retried call never charges or
dispatches twice.

## Thirty seconds

Your agents are already calling internal tools. Nobody can say which agent was
allowed to make a given call, what it cost, or whether a retry ran it twice.

Agent Middleware API puts one enforceable economic boundary in front of those
tools. An agent authenticates with a wallet-scoped key, receives an
Ed25519-signed permit bound to specific tools, scopes, budget, and expiry, and
invokes through a governed MCP gateway. The call is debited against a real
ledger, returns a signed receipt, and lands on a per-wallet hash chain you can
verify after the fact. Replay the same idempotency key and you get the original
receipt back — no second dispatch, no second debit. Ask for something outside
the permit and you get a denial with a concrete reason, also receipted.

It self-hosts, it's MIT-licensed, and you can prove the whole loop on your
laptop in one command.

## Two minutes (design-partner version)

**The problem.** Teams running internal agents against MCP-style tools have an
authorization story ("who can call what") and no economic story. There is no
budget that binds, no artifact proving a specific call was authorized, and no
guarantee that a retried or crashed call doesn't spend twice. Retry logic in
agent frameworks makes this worse, not better: agents retry aggressively by
design.

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
- **Evidence you can hand an auditor.** Signed receipts for success, denial,
  *and* failure, linked to permits, ledger entries, and a verifiable per-wallet
  hash chain.

**Why believe it.** The proof is executable, not asserted:

| Command | What it proves |
|---|---|
| `make prove-trust-plane` | The full permit → invoke → charge → receipt → replay → deny loop |
| `make dogfood-trust-plane` | The same loop against a tool with a real on-disk side effect |
| `make prove-crash-recovery` | Crash consistency across two OS processes killed at commit boundaries |
| `make red-team-trust-plane` | Adversarial attempts against the boundary |

**The ask.** One real internal tool behind the proxy. Not a migration — one
tool, one wallet, one permit, and a walk through the loop. If it doesn't earn
trust in your stack, stop there.

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
allowed. This answers what it cost, proves it was authorized with a signed
artifact, and guarantees a retry doesn't spend twice. The debit and the receipt
are the product; the policy check is table stakes.

**"We already have IAM."** Keep it. This is not an IAM replacement and does not
try to be. IAM says an agent may call a tool; this bounds how much that agent
may spend doing it and produces the evidence afterward.

**"Can't we just log tool calls?"** Logs are written by the same system that
made the call and can be rewritten by anyone with database access. Receipts are
signed and chained, so tampering is *evident*. (Evident, not impossible — a
database administrator who can alter both the data and its chain metadata is
inside the trust boundary, and we say so.)

**"Does exactly-once really hold across the network?"** At our boundary, yes:
one dispatch, one debit, one receipt. A *remote* tool's own side effect is
exactly-once only if that tool also honors the forwarded idempotency key.
Anything else is a lie about distributed systems, and we won't tell it.

**"What's the maturity?"** Production beta, not production complete. Self-host
it, run the proofs, and read `SECURITY_LIMITATIONS.md` before you decide.

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
