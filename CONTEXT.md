# Context: Required Product Vocabulary

Use these definitions in product, strategy, sales, and technical documentation.
They describe the current implementation, not an aspirational architecture.

## Agent-action transaction boundary

The governed boundary through which one agent tool action is authorized. One
accepted idempotency key maps to at most one gateway dispatch and debit plus one
terminal receipt. On the configured upstream MCP path, the gateway persists a
one-shot `dispatch_claimed` state immediately before the network send. Its one
nullable `dispatch_claim_hash` field preserves historical rows while preventing
a later activation from reacquiring an already durable send claim.

The claim ends at the gateway boundary. It proves neither that the downstream
effect occurred nor that it occurred exactly once; remote effect-once behavior
still requires the upstream tool to honor the forwarded idempotency key. This
claim-fencing slice does not change local-tool execution or reservations,
per-tool call slots, quotes, human approval, API-key/JWT authentication, or rate
limiting.

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
Do not describe a durable dispatch claim as proof of a downstream effect or as
one atomic transaction with the upstream system.
