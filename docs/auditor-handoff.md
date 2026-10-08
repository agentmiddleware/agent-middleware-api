# Auditor handoff: verify a signed receipt with no account

One page for the person checking our work. You need two files from us and one
public command. No account, no credential, no call back to our servers.

## What you are checking

Each governed tool call ends with a signed receipt: who was allowed to act,
which tool ran, what it cost, and what happened. The receipt carries an
Ed25519 signature over its exact `signing_input` bytes. If those bytes verify
against our published keys, the receipt is authentic as issued. For the full
story (permit, ledger entry, audit event, dispatch linkage), ask for the
evidence bundle described below.

## Files to request from us

1. **The portable receipt bundle** (`receipt-bundle.json`). We export it from
   `GET /v1/receipts/{receipt_id}/portable`. Fetching it needs our credential,
   so someone inside the deployment must hand it to you. We refuse to export a
   bundle whose stored signature does not verify, so a bundle we hand you
   passed our own check at export time.
2. **A snapshot of the public key set** (`trust-keys.json`). We fetch it from
   `/.well-known/trust-keys.json`, which needs no credential. Ask for the
   snapshot taken with the bundle, not a fresh download: keys rotate, and the
   key that signed an old receipt may since have retired. Retired keys stay
   published so old receipts keep verifying.

## How to verify

Install the verifier from this repo (Python 3.10 or newer, no account needed):

```bash
python -m pip install './b2a_sdk[verify]'
b2a-verify-receipt --bundle receipt-bundle.json --keys trust-keys.json
```

Or in Python:

```python
import json
from b2a_sdk.receipt_verifier import key_set_from_document, verify_bundle

bundle = json.load(open("receipt-bundle.json"))
keys = json.load(open("trust-keys.json"))
result = verify_bundle(bundle, key_set_from_document(keys))
print(result.status, result.reason)
```

Exit codes and statuses are meant to be branched on:

| Code / status | Meaning | Your reading |
|---|---|---|
| `0` / verified | Signature checks out over the exact bytes | Accept as authentic as issued |
| `1` / invalid | Well formed bundle that does not hold together | Treat as tampered, reject |
| `2` / undetermined | Unknown key, malformed input, keys unavailable | Could not check, retry; never report as fraud |

"Could not check" is not "forged". A verifier that conflates the two will
raise a false fraud alarm during a key server outage.

## Rules that keep the check honest

- **Verify the `signing_input` bytes verbatim.** Never re-serialize the parsed
  payload: number and date formatting differs across languages, and a
  re-serialized copy will fail even when the receipt is genuine.
- **Match the bundle's `kid` to a key in your snapshot.** A bundle whose key
  id is absent from the snapshot is undetermined, not invalid.
- **An empty `issuer` means a local or demo deployment.** We set the issuer
  from `PUBLIC_URL`; local runs leave it unset rather than guess. Match by key
  id against the accompanying snapshot instead.
- **Retired keys verify; disabled keys do not.** A retired key signed real
  receipts before rotation and stays published. A disabled key was revoked,
  is withheld from the key set, and anything it signed no longer verifies.
- **Offline verification does not check revocation of permits.** An exported
  permit with a valid signature still verifies offline after revocation. If
  timing matters (was this permit still good at use time), ask us to recheck
  it live against the server.
- **The server check `POST /v1/receipts/verify` covers the receipt signature
  only.** It does not recheck permit, ledger, audit, or dispatch linkage.
  The evidence endpoints do: `GET /v1/receipts/{id}/evidence` (full chained
  checks) and `GET /v1/evidence/{id}` (flat buyer facing bundle with a
  `verification` map). Both need a credential; ask us for the bundle.

## Reading the evidence bundle verification map

Each entry is `ok`, `skipped` (with reason, for example a denial receipt that
has no dispatch), or a failure reason. All five must be `ok` or `skipped`
for the bundle to read as valid:

| Entry | What it proves |
|---|---|
| `receipt_signature` | The receipt signature verifies |
| `permit_signature` | The permit signature verifies and the permit binds the right wallet, tool, and scope |
| `audit_chain` | The linked audit event exists and the hash chain verifies |
| `request_hash` | The request hash ties receipt, audit event, and dispatch together |
| `dispatch_linkage` | The dispatch record matches the receipt (tool, arguments, ledger entry) |

## Our public verification story, stated plainly

Verification always travels as a handed bundle plus public keys. Fetching any
receipt or evidence needs a credential; checking a bundle you were given does
not. The public MCP verify tool is an optional, operator enabled convenience
for unauthenticated clients, off by default and unavailable in
production-like environments. `/.well-known/trust-keys.json` is the only
verification path that is always public. Anything that tells you otherwise is
out of date; please tell us.

Further reading: `docs/quickstart.md` step 8 (timed offline verify walkthrough),
`TRUST_MODEL.md` (what offline verification does and does not establish),
`b2a_sdk/README.md` (verifier install and API).
