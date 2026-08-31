# Context: Required Product Vocabulary

Use these definitions in product, strategy, sales, and technical documentation.
They describe the current implementation, not an aspirational architecture.

## Agent-action transaction boundary

The governed boundary through which one agent tool action is authorized. One
accepted idempotency key maps to at most one gateway dispatch and debit plus one
terminal receipt when the supported path reaches a receiptable terminal
disposition. The claim ends at that boundary; a remote side effect is exactly
once only when the upstream tool also honors the forwarded key. This is a
durable gateway state-machine claim, not an atomic transaction with the
upstream or proof of the downstream effect.

## Consequential autonomous action

An agent-initiated mutation whose duplicate, incorrect, or uncertain execution
has material economic, operational, security, safety, or user impact. It is
intended for agent execution under pre-delegated bounded authority; the current
workflow may still be read-only or human-gated because safe delegation has not
yet been established. A costly read alone does not qualify.

## Retry-sensitive action

An action for which repeating the request after an unknown outcome could create
a second or otherwise harmful effect unless the receiver supplies and honors a
stable idempotency contract.

## Logical action identity

The wallet-scoped canonical governed endpoint plus one accepted idempotency
key, with the logical payload bound by its request hash. The same key with
changed input fails closed.

## Bounded authority consumption

Currently, reservation or retention of configured permit credits or per-tool
call allowance, plus single-use human approval where enabled. This is not a
general-purpose authority-unit ledger and does not claim to count deployments,
deletions, records modified, or other effects unless explicitly modeled.

## Delivery uncertainty

After the one-shot upstream dispatch claim is durable, a missing trustworthy
result becomes `delivery_uncertain`; the debit or allowance remains consumed
and the gateway never automatically redispatches. An operator must reconcile
the downstream effect from the authoritative external system.

## Transaction integrity

The durable linkage of one logical action to its delegated authority,
configured consumption, gateway dispatch/debit state, confirmed or uncertain
outcome, and gateway evidence. It is a crash-safe gateway state machine, not a
single distributed ACID transaction across the network.

## Fixed per-call accounting

An operator configures one credit price for a registered tool call. The gateway
authorizes and debits that amount. It does not derive the amount from tokens,
CPU, GPU, latency, energy, or another measured resource.

## Gateway receipt

An operator-signed record that links the gateway's request and response hashes,
permit, configured credits, outcome, and available dispatch, ledger, and audit
identifiers. A valid signature proves what the gateway signed and linked. It
does not prove that physical work occurred or that a reported amount of a
resource was consumed.

## Offline verification

Verification of a self-contained serialized artifact using available public key
material, without calling the protected application, loading its database
record, or trusting a fresh assertion from the operator. This is shipped for
portable receipt bundles through the SDK verifier and the unauthenticated public
trust-key document. The bundle export itself is wallet-authorized, and the
verifier still trusts the authenticity of the issuer's key distribution unless
the key is pinned through another channel.

## Independently grounded usage

A billable usage measurement whose trust root is outside the seller's or
gateway's unilateral report—for example, a defined metric signed by the
provider, observed by an independent witness, rooted in a TEE or hardware
counter, or established by verifiable computation. A signature over a seller's
own usage assertion preserves attribution and integrity; by itself it does not
make the usage independently grounded.

## Prohibited description

Do not describe the current implementation as **proof of actual compute**. It
implements fixed per-call accounting and operator-signed gateway evidence, not
measurement or seller-independent attestation of physical resource consumption.
Do not describe it as proof of the downstream effect or as one atomic
transaction with an upstream system.
