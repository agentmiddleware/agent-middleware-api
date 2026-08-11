# Denial details (a refusal an agent can act on)

**Audience:** partner integrators and agent authors.

A governed denial used to be a bare reason string. `permit_budget_exceeded`
tells an agent that it failed; it does not tell it whether to ask for two more
credits or two hundred, so the only available move is to retry and fail again.

Every permit denial now carries a `details` object naming the constraint that
was evaluated and the numbers behind it.

## Where it appears

| Surface | Shape |
|---------|-------|
| `POST /mcp/tools/{id}/invoke` | `403 {"detail": {"error": ..., "receipt": {...}, "details": {...}}}` |
| `POST /mcp/messages` (JSON-RPC) | `error.data.details`, beside `error.data.receipt` |
| `POST /v1/permits/verify` | `details` alongside `valid` and `reason` (absent when valid) |
| Governed AWI actions | `detail.details` |
| Signed audit metadata | `denial_details` on the denial's audit event |

The denial receipt is unchanged and still signed; `details` sits beside it,
never instead of it.

## What each denial carries

| Reason | Details |
|--------|---------|
| `permit_budget_exceeded` | `required_credits`, `remaining_credits`, `spent_credits`, `max_credits` |
| `permit_aggregate_value_cap_exceeded` | `required_credits`, `charged_to_date`, `aggregate_value_cap` |
| `permit_max_calls_exceeded` | `tool`, `limit`, `calls_made` |
| `permit_tool_not_allowed` | `requested_tool`, `allowed_tools` |
| `permit_scope_missing` | `required_scopes`, `missing_scopes` |
| `permit_expired` | `expired_at`, `checked_at` |
| `permit_revoked` (any non-active status) | `status`, `revoked_at` |
| `permit_forbidden_field:<name>` | `field`, `forbidden_fields` |
| `permit_signature_invalid` | `key_id` |
| `permit_wallet_mismatch` / `permit_key_mismatch` | `bound_to` only — no values |

Credit amounts are exact decimal strings, not floats. Timestamps are explicit
UTC (`...Z`).

## What details deliberately do not say

**Binding mismatches carry no values.** A caller that presents a permit bound
to a different wallet or key has not proved it is the subject, so the denial
names the binding that failed (`{"bound_to": "subject_wallet_id"}`) and nothing
about which wallet or key the permit actually belongs to. Everything else in
the table describes the caller's *own* permit, which it can already read at
`GET /v1/permits/{permit_id}`.

**Forbidden fields echo the name, never the value.** The value is the thing the
permit forbade carrying.

Reading a denial still requires being authorized for the permit: a foreign
wallet key is refused at `POST /v1/permits/verify` (403) before any verdict is
computed. Details enrich a refusal you were already entitled to see; they do
not widen who can ask.

## Example

```json
{
  "detail": {
    "error": "permit_budget_exceeded",
    "receipt": { "outcome": "denied", "...": "..." },
    "details": {
      "required_credits": "5.0",
      "remaining_credits": "3",
      "spent_credits": "0",
      "max_credits": "3"
    }
  }
}
```

An agent reading that can request a permit for the amount it actually needs —
or, if a human must approve the increase,
[ask for one](permit-requests.md) with the number already in hand.
