"""Golden snapshot of the exact bytes a receipt signature covers.

Refactor gate. The receipt signing input is the product's audit contract:
any change to the field set, key ordering, Decimal/datetime normalization,
or the payload_hash derivation changes what an offline verifier must
reconstruct, and silently invalidates every receipt already issued.

This test freezes three representative receipts to byte-exact canonical
JSON, and freezes the Ed25519 signature over those bytes under a fixed
test seed (Ed25519 is deterministic, so the signature is a second pin on
the same bytes).

If this test fails, the change is either a bug or an intentional receipt
format change. An intentional change requires: (1) a receipt schema version
bump, (2) an entry in CHANGELOG.md, (3) regenerating the golden files with
``UPDATE_RECEIPT_GOLDEN=1 pytest tests/test_receipt_signing_input_snapshot.py``.
Never regenerate to make a refactor PR green.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.db.models import ReceiptModel
from app.services.receipts import ReceiptService
from app.services.signing_keys import canonical_json, sha256_hex

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "receipt_signing_golden"
# Fixed 32-byte seed; NOT a production key. Exists only to make the
# signature pin deterministic.
_TEST_SEED = bytes(range(32))
_FIXED_CREATED_AT = datetime(2026, 9, 14, 17, 0, 0, tzinfo=timezone.utc)


def _base_model(**overrides) -> ReceiptModel:
    fields = dict(
        receipt_id="rcpt_golden_0001",
        idempotency_record_id="idem_golden_0001",
        dispatch_attempt_id="disp_golden_0001",
        permit_id="pmt_golden_0001",
        wallet_id="agt-golden-0001",
        key_id="key_golden_0001",
        tool="golden-path-echo",
        request_hash="a" * 64,
        response_hash="b" * 64,
        ledger_entry_id="led_golden_0001",
        credits_authorized=Decimal("2.50000000"),
        credits_charged=Decimal("2.5"),
        outcome="success",
        reason_code=None,
        audit_event_id="aud_golden_0001",
        approval_id=None,
        constraints_evaluated_json=None,
        created_at=_FIXED_CREATED_AT,
        signature="",
        signature_key_id="sk_golden_0001",
    )
    fields.update(overrides)
    return ReceiptModel(**fields)


CASES = {
    # Current-format success receipt with full governed-dispatch linkage.
    "success_linked": (_base_model(), True),
    # Legacy-format signature: linkage fields excluded from signing input.
    "success_legacy": (_base_model(), False),
    # Signed denial with reason_code and permit-v2 constraints_evaluated.
    "denial_constraints": (
        _base_model(
            receipt_id="rcpt_golden_0002",
            response_hash=None,
            ledger_entry_id=None,
            credits_charged=Decimal("0"),
            outcome="denied",
            reason_code="permit_budget_exceeded",
            constraints_evaluated_json=json.dumps(
                {"max_credits": "2.5", "allowed_tools": ["golden-path-echo"]}
            ),
        ),
        True,
    ),
}


def _signing_input(name: str) -> str:
    model, include_linkage = CASES[name]
    payload = ReceiptService._verification_payload(
        model, include_linkage=include_linkage
    )
    return canonical_json(payload)


def _signature_b64(signing_input: str) -> str:
    key = Ed25519PrivateKey.from_private_bytes(_TEST_SEED)
    return base64.b64encode(key.sign(signing_input.encode())).decode()


@pytest.mark.parametrize("name", sorted(CASES))
def test_receipt_signing_input_is_byte_stable(name: str) -> None:
    signing_input = _signing_input(name)
    signature = _signature_b64(signing_input)
    golden_path = GOLDEN_DIR / f"{name}.json"
    actual = {
        "signing_input": signing_input,
        "signing_input_sha256": sha256_hex(signing_input),
        "signature_b64_over_test_seed": signature,
    }

    if os.environ.get("UPDATE_RECEIPT_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"golden regenerated: {golden_path}")

    assert golden_path.exists(), (
        f"missing golden {golden_path}; run with UPDATE_RECEIPT_GOLDEN=1 once"
    )
    expected = json.loads(golden_path.read_text())
    assert actual["signing_input"] == expected["signing_input"], (
        "receipt signing input changed — this invalidates offline verification "
        "of every issued receipt. See module docstring before regenerating."
    )
    assert actual == expected


def test_payload_hash_is_over_payload_without_itself() -> None:
    """payload_hash must be the hash of the payload *before* it was added."""
    model, _ = CASES["success_linked"]
    payload = ReceiptService._verification_payload(model, include_linkage=True)
    stripped = {k: v for k, v in payload.items() if k != "payload_hash"}
    assert payload["payload_hash"] == sha256_hex(stripped)
