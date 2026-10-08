# Auditor Guide: Verifying a Receipt Without an Account

This page is the handoff. It says which files to ask for, which command
checks them, what each result means, and where the limits are.

## Ask the operator for two files

1. The portable receipt bundle: `GET /v1/receipts/{receipt_id}/portable`
   (exported by someone with access; you do not need an account to check it).
2. A key set snapshot: `GET /.well-known/trust-keys.json` from the issuing
   origin, saved to a file with its SHA-256 hash recorded. JWKS form is at
   `/.well-known/jwks.json` if your tooling prefers it.

## Run this command

```
b2a-verify-receipt --bundle receipt.json --keys trust-keys.json
```

No network access is needed when you pass `--keys`. Verify fully offline
with the snapshot you recorded.

## What each result means

| Exit code | Meaning | Read it as |
|---|---|---|
| 0 | Signature verified | The receipt was signed by the key matching its `kid`, over the exact bytes shown. |
| 1 | Well-formed bundle that does not hold together | Treat as tampered: failed signature, or bytes contradicting the envelope. |
| 2 | Could not determine | Unknown key, malformed input, or bad usage. Not a forgery verdict; get the right key set and rerun. |

A passing check proves the receipt matches the key snapshot you supplied.
It does not prove the snapshot came from the real operator, so record where
you fetched it and its hash.

## The live recheck rule

An exported signature stays checkable forever, but these two questions can
only be answered by asking the gateway now:

- **Was the permit revoked since?** A permit that verifies offline can still
  be revoked on the server. Recheck permits live at `POST /v1/permits/verify`.
- **Was the signing key disabled since?** Retired keys keep verifying history
  on purpose. Disabled keys do not verify at all, and the disabled list is
  only visible live (`GET /v1/signing-keys/`, `/.well-known/trust-keys.json`
  withholds disabled keys).

So: offline verification answers "was this signed then", and only a live
recheck answers "is it still good now". For anything consequential, do both.

## Key rotation in one paragraph

Receipts carry a `kid` naming the key that signed them. Operators rotate by
publishing a new key (`POST /v1/signing-keys/rotate`, bootstrap admin only)
and retiring the old one (`POST /v1/signing-keys/retire`); retired keys stay
published so old receipts keep verifying under their original `kid`. Multiple
keys can read `active` during a rollover window. If your bundle's `kid` is
missing from the key set, that is exit code 2: fetch a fresh key set before
concluding anything.
