# Permit lifecycle (issue, verify, revoke, request, poll, settle)

**Audience:** agent builders and compliance reviewers evaluating the
permit to invoke to receipt loop.
**Product lens:** [`WEDGE.md`](../WEDGE.md). This page names each step, the
status codes, and where to stop polling. For the runnable version, see the
[quickstart](quickstart.md) and the [golden path](golden-path.md).

## Steps

1. **Issue.** `POST /v1/permits` with an `Idempotency-Key` header mints a
   signed budget envelope (tools, scopes, budget, expiry). A repeated key
   with the same payload returns the original permit; the same key with
   different terms is `409`. The subject wallet must be the issuer wallet
   or one it funds, or issuance is `403`.
2. **Verify before acting.** `POST /v1/permits/verify` answers whether one
   wallet plus one tool call would be admitted. Omit the wallet or the tool
   and it answers `permit_verify_context_missing` instead of guessing.
3. **Invoke.** A governed call under the permit reserves budget, dispatches,
   debits the wallet, and returns a signed receipt. Denials name the
   numbers behind the refusal (required versus remaining budget).
4. **Revoke.** `POST /v1/permits/{id}/revoke` cancels a permit. Only the
   issuer wallet (or a bootstrap admin) may revoke: any other caller gets
   `403`. Unknown ids are `404 permit_not_found`. Revoking a permit that
   is already revoked is `409 permit_already_revoked`, so a dashboard can
   tell settled apart from missing.
5. **Request human authority.** `POST /v1/permit-requests` (with
   `Idempotency-Key` and a `justification` the approver reads) pages a
   human via Sentinel and answers `202 {status: "pending", poll_url}`.
6. **Poll.** `GET /v1/permit-requests/{id}` returns `202` while the decision
   is outstanding (`pending`, `minting`) and `200` once it is settled
   (`approved`, `rejected`, `expired`, `failed`). Stop polling on the first
   `200`: every `200` status is terminal.
7. **Settle.** An approval mints an ordinary signed permit exactly once
   (one caller wins the pending to minting claim; the permit id was
   reserved at request time, so a retried mint collides instead of
   duplicating). The minted permit appears in `GET /v1/permits/{id}` and
   drives invokes like any other.

## Terminal request statuses and deadlines

| Status | HTTP on poll | Meaning |
|---|---|---|
| `pending` | 202 | No human decision yet; keep polling. |
| `minting` | 202 | Approved; the permit write is in flight; keep polling. |
| `approved` | 200 | Permit minted; `permit_id` and `permit` are set. Terminal. |
| `rejected` | 200 | The human said no; nothing minted. Terminal. |
| `expired` | 200 | The local decision window elapsed before approval. Terminal. |
| `failed` | 200 | Approval arrived but minting was impossible (for example the wallet no longer covers the budget). A fresh request and a fresh human decision are needed. Terminal. |

The local deadline is `requested_at + PERMIT_REQUEST_TIMEOUT_SECONDS`
(default 3600 seconds). A decision arriving after it mints nothing.
Sentinel itself never expires an approval, so this middleware deadline is
the one that counts.

## What revocation does and does not do

- Revocation is a live check at invoke time. After revocation, new invokes
  are denied with `permit_revoked` and no charge is made.
- Already-issued receipts keep verifying: receipt verification checks the
  receipt signature, not the permit's current status, so the audit trail
  for work done before revocation stays intact.
- An exported permit still carries a valid signature after revocation.
  Offline checks alone cannot see the revocation; recheck a suspect
  permit against the server (`GET /v1/permits/{id}` or the verify
  endpoint) before relying on it.

## Listing

- `GET /v1/permits` lists permits with wallet, status, key, and
  created/expiry filters and pagination. A wallet-scoped key asking
  without filters sees its own permits; the unscoped operator view needs
  a bootstrap admin key.
- Permit requests have no operator-wide list. An agent lists its own via
  `GET /v1/me/permit-requests` (read-only: listing never advances a
  decision). A single request is polled by id.

## What is frozen

- `POST /v1/action-permits` (single-action scoped issuance) is not mounted
  by the normal application and the configured upstream has no qualified
  action binding. Permits remain reusable budget envelopes. Do not build
  or demo against that route.
- Sending action-contract fields to `POST /v1/permits` is refused with
  `action_permit_requires_trusted_issuance`.
- The `simulated` flag on a permit request is true only for local/dev
  auto-approvals (simulation mode with no live Sentinel). Simulated
  requests are refused in production-like environments, and the response
  carries `reason: simulated_auto_approval`, so a demo can label it.
