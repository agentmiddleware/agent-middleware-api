# Break report: signed quotes

Summary: 3 breaks found, 3 fixed and tested, 0 fixed but failing, 0 blocked.

Local SQLite tests only. No production calls, no migrations.

## High: a storable price is charged, then the call fails with no receipt

What broke. Quote and charge a tool at 76613879.62108959 credits. That number passes the 8-place storage check. The wallet is debited for the full amount. The call then raises ChargeCreditMismatchError because the float display of the debit is 76613879.6210896. The caller gets an internal error (HTTP 200 with isError), the quote is already consumed, and there is no receipt. A later retry does not get the work, and a new idempotency key can pay again.

How to reproduce. Register the tool with credits_per_unit_exact set to that string, fund the wallet, issue a quote, and invoke with the quote. Confirmed before the fix: the exception text was `ledger charged 76613879.6210896 != authorized 76613879.62108959`, and the balance had already moved.

Root cause. app/routers/mcp.py `_charge_and_checkpoint` passed `charge_result.amount` (a float) into `aligned_credits_charged`. app/services/governed_metering.py:18 rebuilds that float with `Decimal(str(...))`. The exact debit is `amount_exact`.

Fix. Compare `amount_exact` when it is present. The debit itself was already the quoted credits.

Test. `test_opaque_storable_price_charges_the_quoted_credits` failed before the fix (mismatch, no receipt) and passes after it. The wallet drops by the quoted credits and the receipt shows that same number.

## High: retrying the same idempotency key is refused after a quoted charge

What broke. A quoted invoke succeeds and spends the quote. The caller retries the same body and the same idempotency key, which is the supported way to recover a lost response. The retry is 403 `quote_already_consumed` and does not return the original receipt. A caller who then uses a new key pays a second time.

How to reproduce. Issue a quote, invoke with idempotency key K, invoke again with K and the same quote. Before the fix the second response was `{"detail":"quote_already_consumed"}` with status 403.

Root cause. app/routers/mcp.py checked the quote before the idempotency store. A consumed quote always denied, so the stored success was never replayed. The check is the block that now starts at app/routers/mcp.py:1416.

Fix. If that same key is the one recorded on the quote, replay the stored result and do not consume or charge again. A different key is still `quote_already_consumed`. The same key with different arguments is a conflict and does not charge. If this key spent the quote but the store has no completed result, the call stops before a new charge. The replay branch reads `quoted.quote.quoted_credits` only after `quoted.quote is None` is denied again. `spent_by_this_key` is a bool, so mypy did not keep the earlier `quote is not None` check. The extra check does not change the price: that flag is true only when the quote row is present.

Test. `test_same_idempotency_key_replays_quoted_charge_without_paying_again` failed before the fix and passes after it. One debit of 2 credits, the same receipt id on retry, no further debit.

## Medium: a valid quote is blocked when the list price becomes unusable

What broke. A quote locked 2 credits. The tool's registered price was then set to -5. The invoke refused with `tool_price_invalid` before it looked at the quote. The HTTP result was 200 with an internal error, the wallet did not move, and the locked price was not charged. Money was safe. The price lock was not honored.

How to reproduce. Quote the tool at 2, register the price as -5, invoke with the quote. Before the fix the debit was 0.

Root cause. app/routers/mcp.py read the live price with `_registered_tool_cost` before applying the quote. A bad list price aborted the call. That read is now only used when the caller did not present a quote (app/routers/mcp.py:1462).

Fix. A presented quote supplies the price. An invalid quote still denies, and does not fall through to the live price. A call with no quote still rejects a negative, zero, or non-numeric list price (existing tests still pass).

Test. `test_negative_price_is_refused_and_does_not_mint` failed before the fix (debit 0) and passes after it. The quote request for a negative price is still HTTP 400 `tool_price_invalid`. The later invoke charges 2 and marks the quote consumed.

## Checked, and already holding

- An expired quote cannot be consumed, and a consumed quote cannot be revived after the window. Invoke returns `quote_expired` and the balance does not move.
- A quote for a different tool, including a case change, is `quote_tool_mismatch`. A padded tool name is not found. Nothing is charged.
- The quote body cannot set `quoted_credits`, `currency`, or `category`. The signed price stays the live list price.
- Changing the tool from agent comms at 2 credits to content factory at 50 credits still charges the quoted 2.
- Two overlapping invokes of one quote produce one 200 and one 403, and one debit of 2.

## Open questions

- Sponsor wallet creation accepts a fiat currency and does not store it. There is no currency column to compare with a quote. No schema change was made.
- The charge records the tool's category at invoke time. The quote stores the category from issue time. The credits match the quote. The category label on the ledger can differ. Say if that label must stay the one that was signed.
- Spend time does not check the quote signature again. A database writer who edits `quoted_credits` can change what is charged. No request path does that edit.
- A crash after the debit and before the receipt is still an operator reconciliation case. This pass removes one way to get there (the float mismatch). It does not add a new repair for every later failure.
