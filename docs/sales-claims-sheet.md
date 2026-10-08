# Sales Claims Sheet: What Security Can Truthfully Promise

One page for sellers and design-partner champions. Every claim below is drawn
from the five claims in [security-review-kit.md](security-review-kit.md) §3
plus the known limits in §4 and
[SECURITY_LIMITATIONS.md](../SECURITY_LIMITATIONS.md). Stop at the boundary
stated here. Anything beyond it needs engineering sign-off first.

## The five claims you may make

1. **Charge once under retry.** One idempotency key returns the original
   receipt, with no second execution and no second debit. Reusing a key with
   different content fails closed.
2. **Budget is a cap, not a suggestion.** A permit cannot authorize spend past
   its cap, cumulatively or under concurrency, and a denied call moves no
   money.
3. **Ambiguous outcomes stay answered, never silently redone.** On the
   configured upstream tool, a death after the dispatch checkpoint stays
   charged as `delivery_uncertain` and is never redispatched. A death before
   it nets to zero without dispatching. A local post-effect crash can require
   manual review without a receipt.
4. **Receipts verify offline.** A stranger with no credentials and no access
   to the issuing server can verify a portable receipt against the published
   key set, and a single flipped byte is detected.
5. **Authority before money.** An out-of-scope, unpermitted, expired,
   revoked, or tampered call is denied with a concrete reason before any
   charge, and the denial is itself a signed receipt with no ledger linkage.

## The limits you must state in the same conversation

- Offline verification trusts the issuing origin for key distribution. There
  is no out-of-band pinning yet.
- Audit chains are tamper-evident, not immutable. A database administrator
  can delete rows. There is no external anchoring or transparency log.
- Isolation is application-layer wallet checks only. There is no row-level
  security. Pilots run as one vendor-managed single-tenant project per
  customer, on synthetic or redacted low-sensitivity data.
- The signing key loads from an env var with no KMS. Rotation is redeploy
  plus the retire call in [key-management.md](key-management.md).
- A receipt proves what happened, never what did not. Absence of a receipt
  proves nothing.
- The gateway promise covers the gateway's own dispatch and debit, not the
  downstream effect inside the upstream tool.

## Words you never use

Do not say **immutable** (say tamper-evident). Do not say **exactly-once**
(say at most one debit per accepted key, never a duplicate charge). Do not
say **compliant**, **certified**, **SOC 2**, or **guaranteed delivery** (say
what the five claims cover and name the limits above). Do not promise an
**uptime SLA**, **RTO/RPO**, or coverage for **PHI/PCI** records: all are out
of scope per [SECURITY_LIMITATIONS.md](../SECURITY_LIMITATIONS.md).

## Pilot scope this sheet supports

Paid single-tool pilots with one named internal tool, one engineer, and one
budget. Per-customer signing keys and domains. Synthetic or redacted data
only. Anything shared-tenant, regulated-data, or money-movement goes through
the 30-day validation bar in
[30-day-customer-validation.md](30-day-customer-validation.md) first.
