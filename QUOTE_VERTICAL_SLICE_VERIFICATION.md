# Quote-Locked Pricing Vertical Slice — Implementation Verification

## Status: ✅ COMPLETE ON MAIN

The quote-locked pricing vertical slice described in WEDGE.md is **already fully implemented** on the current main branch (commit `254a4ad`).

## WEDGE.md Promise

> A signed quote can fix the price of one call, and the charge honors it even after the tool's registered price moves.

## Implementation Summary

### Flow

1. **Issue Quote** (`POST /v1/quotes`)
   - Agent requests a quote for `(wallet_id, tool)`
   - Service reads the tool's live price and freezes it into a signed statement
   - Returns: `quote_id`, `quoted_credits`, `expires_at`, `signature`, `key_id`

2. **Price Moves**
   - The tool's registered price can change (up or down)
   - The quote remains valid and locked to the original price

3. **Invoke with Quote** (`POST /mcp/tools/{tool}/invoke` with `mcpContext.quote_id`)
   - Service validates the quote (not expired, correct wallet/tool, not consumed)
   - Service consumes the quote atomically (single-use protection)
   - Service uses `quoted_credits` instead of live price for:
     - Policy evaluation
     - Permit budget check
     - Wallet charge
   - Receipt shows the quoted amount

4. **Charge Uses Quoted Amount**
   - The wallet is charged exactly `quoted_credits`
   - The ledger entry reflects the quoted amount
   - The signed receipt attests to the quoted amount

### Key Files

| File | Role |
|------|------|
| `app/services/quotes.py` | Core quote service: create, validate, consume, release |
| `app/routers/quotes.py` | HTTP endpoints: `POST /v1/quotes`, `GET /v1/quotes/{id}` |
| `app/routers/mcp.py` | Integration: quote validation (L702-734), consumption (L1193-1227), charge (L1233-1251), release on insufficient funds (L1277-1282) |
| `app/trust/quotes.py` | Trust-plane facade (re-exports) |
| `migrations/versions/031_quotes.py` | Database schema |
| `docs/signed-quotes.md` | Operator documentation |

### Security Properties

1. **Single-use**: Atomic `UPDATE ... WHERE status='active' AND expires_at > now` (L295-310 of `quotes.py`)
2. **Signed**: Ed25519 signature over canonical payload, verifiable offline
3. **Expiry-checked**: `QUOTE_TTL_SECONDS` (default 600s, clamped 30-3600s)
4. **Wallet-scoped**: Quote validation requires exact wallet match
5. **Tool-scoped**: Quote validation requires exact tool match
6. **No silent repricing**: Invalid quotes deny the invoke (403), never fall back to live price
7. **Compensating release**: If quote consumed but charge fails (insufficient funds), quote is released back to `active` (L1277-1282 of `mcp.py`)

### Test Coverage

All tests passing in `tests/test_signed_quotes.py` (14 tests):

- ✅ Quote carries live price and window
- ✅ Signature verifies, detects tampering, survives consumption
- ✅ **Quote locks price against a hike** (WEDGE.md promise)
- ✅ **Quote locks price against a cut** (commitment, not best-price)
- ✅ Invoke without quote pays live price
- ✅ **Quote is single-use** (second invoke denied)
- ✅ **Expired quote denies** (no silent repricing)
- ✅ **Wrong wallet/tool quote refused** (no charge)
- ✅ Quote returned when charge never lands (compensation)
- ✅ Permit budget checked against quoted price
- ✅ Quote read is wallet-scoped
- ✅ Quoting someone else's wallet refused
- ✅ Concurrent consume spends quote once
- ✅ Wallet can list its own quotes

Additional verification tests in `tests/test_quote_vertical_slice.py` (3 tests):

- ✅ Complete vertical slice: quote → price hike → charge uses quote
- ✅ All negative paths deny without charge
- ✅ Price cuts also honored (commitment property)

### Logging Security

- **Quote IDs** are logged in audit metadata (appropriate — they're identifiers, not secrets)
- **Signatures, keys, credits** are NOT logged (verified: no logger calls in `quotes.py` or `quotes.py` router)
- Request payloads hashed before storage (`sha256_hex(effective_request_payload)`)

## What Was NOT Changed

Per the task requirements, the following were not modified:

- ❌ Dispatch-uncertainty / remote-dispatch state machine (untouched)
- ❌ `/v1/permit-requests` or Sentinel (untouched)
- ❌ Discovery catalogs (no quote field needed — quote is optional in `mcpContext`)
- ❌ Proof surfaces (untouched)

## Evidence

Run the tests:

```bash
python3 -m pytest tests/test_signed_quotes.py -v
python3 -m pytest tests/test_quote_vertical_slice.py -v
```

All 17 tests pass (14 original + 3 new verification tests).

## Conclusion

The quote-locked pricing vertical slice is **already complete** and **fully tested** on main. The implementation:

1. ✅ Issues signed quotes that lock the price of one call
2. ✅ Honors the quote even after the tool's registered price moves (up or down)
3. ✅ Consumes quotes atomically (single-use)
4. ✅ Denies invalid quotes without silent repricing (expired, wrong wallet, wrong tool, already consumed)
5. ✅ Releases consumed quotes if the charge fails (compensation)
6. ✅ Does not log secrets
7. ✅ Has comprehensive test coverage

No implementation work was required. This document and the new verification tests confirm that the WEDGE.md promise is already delivered.
