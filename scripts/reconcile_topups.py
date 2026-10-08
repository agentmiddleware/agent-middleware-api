#!/usr/bin/env python3
"""Nightly minted-vs-settled reconciliation report (ledger-internal half).

Checklist item 15 in docs/settlement-rails.md: no job asserts that live
credits are backed by verified settlements. This script prints every
Stripe-minted credit (one row per payment intent, CSV) plus totals, so the
operator can compare cumulative minted credits against Stripe dashboard
payouts. It also flags Stripe refunds that reference a payment intent with
no matching mint row, which is the shape a missed or dropped mint webhook
leaves behind, and exits nonzero when any are found.

This is the ledger-internal half only. It cannot see Stripe's side; the
operator comparison against Stripe payouts is the other half.

Usage:
  python scripts/reconcile_topups.py
  python scripts/reconcile_topups.py --format json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _render_csv(summary: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["payment_intent_id", "wallet_id", "amount_exact", "timestamp"])
    for mint in summary["mints"]:
        writer.writerow(
            [
                mint["payment_intent_id"],
                mint["wallet_id"],
                mint["amount_exact"],
                mint["timestamp"],
            ]
        )
    return buffer.getvalue()


def _render_text(summary: dict[str, Any]) -> str:
    lines = [
        "minted_count=%d minted_total=%s refunded_count=%d refunded_total=%s "
        "net_minted=%s"
        % (
            summary["minted_count"],
            summary["minted_total_exact"],
            summary["refunded_count"],
            summary["refunded_total_exact"],
            summary["net_minted_exact"],
        ),
        "Compare minted_total against Stripe dashboard payouts; "
        "any gap means an over-mint or a missed webhook.",
    ]
    for orphan in summary["orphan_refunds"]:
        lines.append(
            "ORPHAN_REFUND entry=%s wallet=%s intent=%s amount=%s"
            % (
                orphan["entry_id"],
                orphan["wallet_id"],
                orphan["payment_intent_id"],
                orphan["amount_exact"],
            )
        )
    for unlinked in summary["unlinked_refunds"]:
        lines.append(
            "UNLINKED_REFUND entry=%s wallet=%s description=%r (non-Stripe "
            "refund, review manually)"
            % (
                unlinked["entry_id"],
                unlinked["wallet_id"],
                unlinked["description"],
            )
        )
    return "\n".join(lines)


async def _summarize() -> dict[str, Any]:
    from app.services.agent_money import get_agent_money

    return await get_agent_money().get_settlement_summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("text", "csv", "json"),
        default="text",
        help="Report format (default: text).",
    )
    args = parser.parse_args(argv)

    summary = asyncio.run(_summarize())
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif args.format == "csv":
        print(_render_csv(summary), end="")
    else:
        print(_render_text(summary))

    if summary["orphan_refunds"]:
        print(
            "FAIL: %d refund(s) reference payment intents with no mint row"
            % len(summary["orphan_refunds"]),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
